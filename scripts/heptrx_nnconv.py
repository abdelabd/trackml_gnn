import os
import os.path as osp
import math

import mlflow
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch_geometric.transforms as T
from torch_geometric.data import DataLoader
from torch_geometric.utils import normalized_cut
from torch_geometric.nn import (NNConv, graclus, max_pool, max_pool_x,
                                global_mean_pool)

torch.backends.cudnn.benchmark = True
torch.backends.cudnn.enabled = True

from datasets.hitgraphs import HitGraphDataset

import tqdm
import argparse
directed = False
sig_weight = 1.0
bkg_weight = 1.0
lr = 0.01
hidden_dim = 64
n_iters = 6

from training.gnn import GNNTrainer

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print('using device %s'%device)

import logging

def main(args):

    path = osp.join(os.environ['GNN_TRAINING_DATA_ROOT'], args.dataset)
    print(path)


    train_batch_size = args.train_batch_size
    valid_batch_size = args.validate_batch_size
    n_epochs = args.num_epochs

    full_dataset = HitGraphDataset(path, directed=directed, categorical=args.categorized)
    fulllen = len(full_dataset)
    tv_frac = args.tv_fraction
    tv_num = math.ceil(fulllen*tv_frac)
    splits = np.cumsum([fulllen-tv_num,0,tv_num])
    print(fulllen, splits)

    with mlflow.start_run() as run:
        train_dataset = torch.utils.data.Subset(full_dataset,np.arange(start=0,stop=splits[0]))
        valid_dataset = torch.utils.data.Subset(full_dataset,np.arange(start=splits[1],stop=splits[2]))
        train_loader = DataLoader(train_dataset, batch_size=train_batch_size, pin_memory=True)
        valid_loader = DataLoader(valid_dataset, batch_size=valid_batch_size, shuffle=False)

        train_samples = len(train_dataset)
        valid_samples = len(valid_dataset)

        d = full_dataset
        num_features = d.num_features
        num_classes = d[0].y.dim() if d[0].y.dim() == 1 else d[0].y.size(1)

        if args.categorized:
            if not args.forcecats:
                num_classes = int(d[0].y.max().item()) + 1 if d[0].y.dim() == 1 else d[0].y.size(1)
            else:
                num_classes = args.cats


        #the_weights = np.array([1., 1., 1., 1.]) #[0.017, 1., 1., 10.]
        #todo: Must match number of categories
        the_weights = np.array([1., 1.])
        trainer = GNNTrainer(category_weights = the_weights,
                             output_dir=args.output_dir, device=device,
                             mlflow_client=mlflow.tracking.MlflowClient(),
                             mlflow_run_id=run.info.run_id)

        trainer.logger.setLevel(logging.DEBUG)
        strmH = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        strmH.setFormatter(formatter)
        trainer.logger.addHandler(strmH)

        #example lr scheduling definition
        def lr_scaling(optimizer):
            from torch.optim.lr_scheduler import ReduceLROnPlateau
            return ReduceLROnPlateau(optimizer, mode='min', verbose=True,
                                     min_lr=5e-7, factor=0.2,
                                     threshold=0.01, patience=5)


        trainer.build_model(name=args.model, loss_func=args.loss,
                            optimizer=args.optimizer, learning_rate=args.lr, lr_scaling=lr_scaling,
                            input_dim=num_features, hidden_dim=args.hidden_dim, n_iters=args.n_iters,
                            output_dim=num_classes)

        trainer.print_model_summary()

        train_summary = trainer.train(train_loader, n_epochs, valid_data_loader=valid_loader)

        print(train_summary)


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument('--categorized', '-c', action='store_true', default=False, help='Does the model you want to train have explicit categories?')
    parser.add_argument('--forcecats', action='store_true', default=False, help='Do we want to force the number of categories?')
    parser.add_argument('--cats', default=1, type=int, help='Number of categories to force')
    parser.add_argument('--optimizer', '-o', default='Adam', help='Optimizer to use for training.')
    parser.add_argument('--model', '-m', default='EdgeNet2', help='The model to train.')
    parser.add_argument('--loss', '-l', default='binary_cross_entropy', help='Loss function to use in training.')
    parser.add_argument('--lr', default=0.001, type=float, help='The starting learning rate.')
    parser.add_argument('--hidden_dim', default=64, type=int, help='Latent space size.')
    parser.add_argument('--n_iters', default=6, type=int, help='Number of times to iterate the graph.')
    parser.add_argument('--dataset', '-d', default='single_photon')
    parser.add_argument('--output-dir', default='/data/gnn_code/hgcal_ldrd/output')
    parser.add_argument('--num-epochs', type=int, default=50)
    parser.add_argument('--train-batch-size', type=int, default=1)
    parser.add_argument('--validate-batch-size', type=int, default=1)
    parser.add_argument('--tv-fraction', type=float, default=0.20)

    args = parser.parse_args()
    main(args)
