import __init__
from ogb.nodeproppred import Evaluator
import torch
from torch.utils.data import DataLoader
from args import ArgsInit
from ogb.linkproppred import PygLinkPropPredDataset, Evaluator
from model import DeeperGCN, LinkPredictor
from utils.ckpt_util import save_ckpt
import logging
import time
from torch.utils.tensorboard import SummaryWriter
import train
import pdb
import pruning
import copy

def main_fixed_mask(args, imp_num, rewind_weight_mask, rewind_predict_weight, resume_train_ckpt=None):

    device = torch.device("cuda:" + str(args.device))
    dataset = PygLinkPropPredDataset(name=args.dataset)
    data = dataset[0]
    # Data(edge_index=[2, 2358104], edge_weight=[2358104, 1], edge_year=[2358104, 1], x=[235868, 128])
    split_edge = dataset.get_edge_split()
    evaluator = Evaluator(args.dataset)

    x = data.x.to(device)

    edge_index = data.edge_index.to(device)

    args.in_channels = data.x.size(-1)
    args.num_tasks = 1

    model = DeeperGCN(args).to(device)
    pruning.add_mask(model, args)
    predictor = LinkPredictor(args).to(device)
    model.load_state_dict(rewind_weight_mask)
    predictor.load_state_dict(rewind_predict_weight)
    adj_spar, wei_spar = pruning.print_sparsity(model, args)

    for name, param in model.named_parameters():
        if 'mask' in name:
            param.requires_grad = False

    optimizer = torch.optim.Adam(list(model.parameters()) + list(predictor.parameters()), lr=args.lr)
    # results = {}
    results = {'epoch': 0 }
    keys = ['highest_valid', 'final_train', 'final_test', 'highest_train']
    hits = ['Hits@10', 'Hits@50', 'Hits@100']
    
    for key in keys:
        results[key] = {k: 0 for k in hits}
    results['adj_spar'] = adj_spar
    results['wei_spar'] = wei_spar
    
    start_epoch = 1
    if resume_train_ckpt is not None:
        
        start_epoch = resume_train_ckpt['epoch']
        ori_model_dict = model.state_dict()
        over_lap = {k : v for k, v in resume_train_ckpt['model_state_dict'].items() if k in ori_model_dict.keys()}
        ori_model_dict.update(over_lap)
        model.load_state_dict(ori_model_dict)
        predictor.load_state_dict(resume_train_ckpt['predictor_state_dict'])
        print("(FIXED MASK) Resume at epoch:[{}] len:[{}/{}]!".format(resume_train_ckpt['epoch'], len(over_lap.keys()), len(ori_model_dict.keys())))
        optimizer.load_state_dict(resume_train_ckpt['optimizer_state_dict'])
        adj_spar, wei_spar = pruning.print_sparsity(model, args)

    for epoch in range(start_epoch, args.fix_epochs + 1):

        t0 = time.time()
        epoch_loss = train.train_fixed(model, predictor, x, edge_index, split_edge, optimizer, args.batch_size, args)
        result = train.test(model, predictor, x, edge_index, split_edge, evaluator, args.batch_size, args)
        # return a tuple
        k = 'Hits@50'
        train_result, valid_result, test_result = result[k]

        if train_result > results['highest_train'][k]:
            results['highest_train'][k] = train_result

        if valid_result > results['highest_valid'][k]:
            results['highest_valid'][k] = valid_result
            results['final_train'][k] = train_result
            results['final_test'][k] = test_result
            results['epoch'] = epoch
            pruning.save_all(model, predictor, 
                                    rewind_weight_mask, 
                                    optimizer, 
                                    imp_num, 
                                    epoch, 
                                    args.model_save_path, 
                                    'IMP{}_fixed_ckpt'.format(imp_num))

        epoch_time = (time.time() - t0) / 60
        print(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()) + ' | ' +
              'IMP:[{}] (FIX Mask) Epoch:[{}/{}] LOSS:[{:.4f}] Train :[{:.2f}] Valid:[{:.2f}] Test:[{:.2f}] | Update Test:[{:.2f}] at epoch:[{}] Time:[{:.2f}min]'
              .format(imp_num, epoch, args.fix_epochs, epoch_loss, train_result * 100,
                                                               valid_result * 100,
                                                               test_result * 100, 
                                                               results['final_test'][k] * 100,
                                                               results['epoch'],
                                                               epoch_time))
    print("=" * 120)
    print("INFO final: IMP:[{}], Train:[{:.2f}]  Best Val:[{:.2f}] at epoch:[{}] | Final Test Acc:[{:.2f}] Adj:[{:.2f}%] Wei:[{:.2f}%]"
        .format(imp_num,    results['final_train'][k] * 100,
                            results['highest_valid'][k] * 100,
                            results['epoch'],
                            results['final_test'][k] * 100,
                            results['adj_spar'],
                            results['wei_spar']))
    print("=" * 120)



def main_get_mask(args, imp_num, rewind_weight_mask=None, rewind_predict_weight=None, resume_train_ckpt=None):

    device = torch.device("cuda:" + str(args.device))
    dataset = PygLinkPropPredDataset(name=args.dataset)
    data = dataset[0]
    
    # Data(edge_index=[2, 2358104], edge_weight=[2358104, 1], edge_year=[2358104, 1], x=[235868, 128])
    split_edge = dataset.get_edge_split()
    evaluator = Evaluator(args.dataset)

    x = data.x.to(device)

    edge_index = data.edge_index.to(device)

    args.in_channels = data.x.size(-1)
    args.num_tasks = 1

    model = DeeperGCN(args).to(device)
    pruning.add_mask(model, args)
    predictor = LinkPredictor(args).to(device)
    pruning.add_trainable_mask_noise(model, args, c=1e-4)
    optimizer = torch.optim.Adam(list(model.parameters()) + list(predictor.parameters()), lr=args.lr)

    results = {'epoch': 0 }
    keys = ['highest_valid', 'final_train', 'final_test', 'highest_train']
    hits = ['Hits@10', 'Hits@50', 'Hits@100']

    for key in keys:
        results[key] = {k: 0 for k in hits}

    start_epoch = 1
    if resume_train_ckpt:
        
        start_epoch = resume_train_ckpt['epoch']
        rewind_weight_mask = resume_train_ckpt['rewind_weight_mask']
        ori_model_dict = model.state_dict()
        over_lap = {k : v for k, v in resume_train_ckpt['model_state_dict'].items() if k in ori_model_dict.keys()}
        ori_model_dict.update(over_lap)
        model.load_state_dict(ori_model_dict)
        print("Resume at IMP:[{}] epoch:[{}] len:[{}/{}]!".format(imp_num, resume_train_ckpt['epoch'], len(over_lap.keys()), len(ori_model_dict.keys())))
        optimizer.load_state_dict(resume_train_ckpt['optimizer_state_dict'])
        adj_spar, wei_spar = pruning.print_sparsity(model, args)
    else:
        rewind_weight_mask = copy.deepcopy(model.state_dict())
        rewind_predict_weight = copy.deepcopy(predictor.state_dict())

    for epoch in range(start_epoch, args.mask_epochs + 1):

        t0 = time.time()     
        
        epoch_loss, prune_info_dict = train.train_mask(model, predictor, 
                                                                 x, 
                                                                 edge_index, 
                                                                 split_edge, 
                                                                 optimizer, args)

        result = train.test(model, predictor, 
                                   x, 
                                   edge_index, 
                                   split_edge, 
                                   evaluator, 
                                   args.batch_size, args)

        k = 'Hits@50'
        train_result, valid_result, test_result = result[k]
        if train_result > results['highest_train'][k]:
            results['highest_train'][k] = train_result

        if valid_result > results['highest_valid'][k]:
            results['highest_valid'][k] = valid_result
            results['final_train'][k] = train_result
            results['final_test'][k] = test_result
            results['epoch'] = epoch
            pruning.save_all(model, predictor, 
                                    rewind_weight_mask, 
                                    optimizer, 
                                    imp_num, 
                                    epoch, 
                                    args.model_save_path, 
                                    'IMP{}_train_ckpt'.format(imp_num))

        epoch_time = (time.time() - t0) / 60
        print(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()) + ' | ' +
              'IMP:[{}] (GET Mask) Epoch:[{}/{}] LOSS:[{:.4f}] Train :[{:.2f}] Valid:[{:.2f}] Test:[{:.2f}] | Update Test:[{:.2f}] at epoch:[{}] | Adj[{:.3f}%] Wei[{:.3f}%] Time:[{:.2f}min]'
              .format(imp_num, epoch, args.mask_epochs, 
                                      epoch_loss, 
                                      train_result * 100,
                                      valid_result * 100,
                                      test_result * 100,
                                      results['final_test'][k] * 100,
                                      results['epoch'],
                                      prune_info_dict['adj_spar'], 
                                      prune_info_dict['wei_spar'],
                                      epoch_time))

    rewind_weight_mask, adj_spar, wei_spar = pruning.change(rewind_weight_mask, model, args)
    print('-' * 100)
    print("INFO : IMP:[{}] (GET MASK) Final Result Train:[{:.2f}]  Valid:[{:.2f}]  Test:[{:.2f}] | Adj:[{:.3f}%] Wei:[{:.3f}%]"
        .format(imp_num, results['final_train'][k] * 100,
                         results['highest_valid'][k] * 100,
                         results['final_test'][k] * 100,
                         adj_spar, 
                         wei_spar))
    print('-' * 100)
    return rewind_weight_mask, rewind_predict_weight


if __name__ == "__main__":

    args = ArgsInit().save_exp()
    imp_num = args.imp_num
    percent_list = [(1 - (1 - 0.05) ** (i + 1), 1 - (1 - 0.2) ** (i + 1)) for i in range(20)]
    
    args.pruning_percent_adj, args.pruning_percent_wei = percent_list[imp_num - 1]
    pruning.print_args(args, 80)
    pruning.setup_seed(666)
    print("INFO: IMP:[{}] Pruning adj[{:.6f}], wei[{:.6f}]".format(imp_num, args.pruning_percent_adj, args.pruning_percent_wei))

    resume_train_ckpt = None
    if args.resume_dir:
        resume_train_ckpt = torch.load(args.resume_dir)
        start_imp = resume_train_ckpt['imp_num']
        rewind_weight_mask = resume_train_ckpt['rewind_weight_mask']
        if 'fixed_ckpt' in args.resume_dir:
            main_fixed_mask(args, start_imp, rewind_weight_mask, resume_train_ckpt)
            exit()

    rewind_weight_mask, rewind_predict_weight = main_get_mask(args, imp_num, resume_train_ckpt)
    print("INFO: IMP[{}] Begin Retrain!".format(imp_num))
    main_fixed_mask(args, imp_num, rewind_weight_mask, rewind_predict_weight, resume_train_ckpt=None)