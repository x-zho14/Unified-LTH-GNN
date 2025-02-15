import __init__
import argparse
import uuid
import logging
import time
import os
import sys
from utils.logger import create_exp_dir
import glob


class ArgsInit(object):
    def __init__(self):
        parser = argparse.ArgumentParser(description='DeeperGCN')

        ### pruning settings
        parser.add_argument('--s1', type=float, default=0.0001,help='scale sparse rate (default: 0.0001)')
        parser.add_argument('--s2', type=float, default=0.0001,help='scale sparse rate (default: 0.0001)')
        parser.add_argument('--pruning_percent_wei', type=float, default=0.1)
        parser.add_argument('--pruning_percent_adj', type=float, default=0.1)
        parser.add_argument('--resume_dir', type=str, default='')
        parser.add_argument('--seed', type=int, default=10, help='which seed to use if any (default: 0)')
        parser.add_argument('--mask_epochs', type=int, default=200,
                            help='number of epochs to train (default: 500)')
        parser.add_argument('--fix_epochs', type=int, default=500,
                            help='number of epochs to train (default: 500)')                            
        parser.add_argument('--fixed', default='', type=str, help='{all_fixed, only_adj, only_wei, no_fixed}')

        # parser.add_argument('--baseline', action='store_true')
        # dataset
        parser.add_argument('--dataset', type=str, default='ogbn-arxiv',
                            help='dataset name (default: ogbn-arxiv)')
        parser.add_argument('--self_loop', action='store_true')
        # training & eval settings
        parser.add_argument('--use_gpu', action='store_true')
        parser.add_argument('--device', type=int, default=0,
                            help='which gpu to use if any (default: 0)')
        parser.add_argument('--epochs', type=int, default=500,
                            help='number of epochs to train (default: 500)')
        parser.add_argument('--lr', type=float, default=0.01,
                            help='learning rate set for optimizer.')
        parser.add_argument('--dropout', type=float, default=0.5)
        # model
        parser.add_argument('--num_layers', type=int, default=3,
                            help='the number of layers of the networks')
        parser.add_argument('--mlp_layers', type=int, default=1,
                            help='the number of layers of mlp in conv')
        parser.add_argument('--in_channels', type=int, default=128,
                            help='the dimension of initial embeddings of nodes')
        parser.add_argument('--hidden_channels', type=int, default=128,
                            help='the dimension of embeddings of nodes')
        parser.add_argument('--block', default='res+', type=str,
                            help='graph backbone block type {res+, res, dense, plain}')
        parser.add_argument('--conv', type=str, default='gen',
                            help='the type of GCNs')
        parser.add_argument('--gcn_aggr', type=str, default='max',
                            help='the aggregator of GENConv [mean, max, add, softmax, softmax_sg, softmax_sum, power, power_sum]')
        parser.add_argument('--norm', type=str, default='batch',
                            help='the type of normalization layer')
        parser.add_argument('--num_tasks', type=int, default=1,
                            help='the number of prediction tasks')
        # learnable parameters
        parser.add_argument('--t', type=float, default=1.0,
                            help='the temperature of SoftMax')
        parser.add_argument('--p', type=float, default=1.0,
                            help='the power of PowerMean')
        parser.add_argument('--y', type=float, default=0.0,
                            help='the power of degrees')
        parser.add_argument('--learn_t', action='store_true')
        parser.add_argument('--learn_p', action='store_true')
        parser.add_argument('--learn_y', action='store_true')
        # message norm
        parser.add_argument('--msg_norm', action='store_true')
        parser.add_argument('--learn_msg_scale', action='store_true')
        # save model
        parser.add_argument('--model_save_path', type=str, default='model_ckpt',
                            help='the directory used to save models')
        parser.add_argument('--save', type=str, default='CKPTs', help='experiment name')
        # load pre-trained model
        parser.add_argument('--model_load_path', type=str, default='ogbn_arxiv_pretrained_model.pth',
                            help='the path of pre-trained model')

        self.args = parser.parse_args()

    def save_exp(self):
        # self.args.save = '{}-B_{}-C_{}-L_{}-F_{}-DP_{}' \
        #             '-GA_{}-T_{}-LT_{}-P_{}-LP_{}-Y_{}-LY_{}' \
        #             '-MN_{}-LS_{}'.format(self.args.save, self.args.block, self.args.conv,
        #                                   self.args.num_layers, self.args.hidden_channels,
        #                                   self.args.dropout, self.args.gcn_aggr,
        #                                   self.args.t, self.args.learn_t, 
        #                                   self.args.p, self.args.learn_p,
        #                                   self.args.y, self.args.learn_y,
        #                                   self.args.msg_norm, self.args.learn_msg_scale)

        # self.args.save = 'log/{}-{}-{}'.format(self.args.save, time.strftime("%Y%m%d-%H%M%S"), str(uuid.uuid4()))
        self.args.model_save_path = os.path.join(self.args.save, self.args.model_save_path)
        create_exp_dir(self.args.save, scripts_to_save=glob.glob('*.py'))
        log_format = '%(asctime)s %(message)s'
        logging.basicConfig(stream=sys.stdout,
                            level=logging.INFO,
                            format=log_format,
                            datefmt='%m/%d %I:%M:%S %p')
        # fh = logging.FileHandler(os.path.join(self.args.model_save_path, 'log.txt'))
        # fh.setFormatter(logging.Formatter(log_format))
        # logging.getLogger().addHandler(fh)

        return self.args
