import __init__
from ogb.nodeproppred import Evaluator
import torch
import torch.nn.functional as F
from torch_geometric.utils import to_undirected, add_self_loops
from args import ArgsInit
from ogb.nodeproppred import PygNodePropPredDataset
from model import DeeperGCN
from utils.ckpt_util import save_ckpt
import logging
import pruning
import copy
import time
import pdb
import warnings
warnings.filterwarnings('ignore')

@torch.no_grad()
def test(model, x, edge_index, y_true, split_idx, evaluator):
    model.eval()
    out = model(x, edge_index)

    y_pred = out.argmax(dim=-1, keepdim=True)

    train_acc = evaluator.eval({
        'y_true': y_true[split_idx['train']],
        'y_pred': y_pred[split_idx['train']],
    })['acc']
    valid_acc = evaluator.eval({
        'y_true': y_true[split_idx['valid']],
        'y_pred': y_pred[split_idx['valid']],
    })['acc']
    test_acc = evaluator.eval({
        'y_true': y_true[split_idx['test']],
        'y_pred': y_pred[split_idx['test']],
    })['acc']

    return train_acc, valid_acc, test_acc


def train(model, x, edge_index, y_true, train_idx, optimizer, args):

    model.train()
    optimizer.zero_grad()
    pred = model(x, edge_index)[train_idx]
    loss = F.nll_loss(pred, y_true.squeeze(1)[train_idx])
    loss.backward()
    pruning.subgradient_update_mask(model, args) # l1 norm
    optimizer.step()
    return loss.item()

def train_fixed(model, x, edge_index, y_true, train_idx, optimizer, args):

    model.train()
    optimizer.zero_grad()
    pred = model(x, edge_index)[train_idx]
    loss = F.nll_loss(pred, y_true.squeeze(1)[train_idx])
    loss.backward()
    optimizer.step()
    return loss.item()


def main_fixed_mask(args, imp_num, rewind_weight_mask, resume_train_ckpt=None):

    device = torch.device("cuda:" + str(args.device))
    dataset = PygNodePropPredDataset(name=args.dataset)
    data = dataset[0]
    split_idx = dataset.get_idx_split()
    evaluator = Evaluator(args.dataset)

    x = data.x.to(device)
    y_true = data.y.to(device)
    train_idx = split_idx['train'].to(device)

    edge_index = data.edge_index.to(device)
    edge_index = to_undirected(edge_index, data.num_nodes)

    if args.self_loop:
        edge_index = add_self_loops(edge_index, num_nodes=data.num_nodes)[0]

    args.in_channels = data.x.size(-1)
    args.num_tasks = dataset.num_classes

    model = DeeperGCN(args).to(device)
    pruning.add_mask(model, args.num_layers)
    model.load_state_dict(rewind_weight_mask)
    adj_spar, wei_spar = pruning.print_sparsity(model, args)
    
    for name, param in model.named_parameters():
        if 'mask' in name:
            param.requires_grad = False

    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)
    results = {'highest_valid': 0, 'final_train': 0, 'final_test': 0, 'highest_train': 0, 'epoch': 0}
    results['adj_spar'] = adj_spar
    results['wei_spar'] = wei_spar

    start_epoch = 1
    if resume_train_ckpt:
        
        start_epoch = resume_train_ckpt['epoch']
        ori_model_dict = model.state_dict()
        over_lap = {k : v for k, v in resume_train_ckpt['model_state_dict'].items() if k in ori_model_dict.keys()}
        ori_model_dict.update(over_lap)
        model.load_state_dict(ori_model_dict)
        print("(FIXED MASK) Resume at epoch:[{}] len:[{}/{}]!".format(resume_train_ckpt['epoch'], len(over_lap.keys()), len(ori_model_dict.keys())))
        optimizer.load_state_dict(resume_train_ckpt['optimizer_state_dict'])
        adj_spar, wei_spar = pruning.print_sparsity(model, args)

    for epoch in range(start_epoch, args.fix_epochs + 1):
    
        epoch_loss = train_fixed(model, x, edge_index, y_true, train_idx, optimizer, args)
        result = test(model, x, edge_index, y_true, split_idx, evaluator)
        train_accuracy, valid_accuracy, test_accuracy = result

        if valid_accuracy > results['highest_valid']:
            results['highest_valid'] = valid_accuracy
            results['final_train'] = train_accuracy
            results['final_test'] = test_accuracy
            results['epoch'] = epoch
            #pruning.save_all(model, rewind_weight_mask, optimizer, imp_num, epoch, args.model_save_path, 'IMP{}_fixed_ckpt'.format(imp_num))

        print(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()) + ' | ' +
              'IMP:[{}] (FIX Mask) Epoch:[{}/{}]\t LOSS:[{:.4f}] Train :[{:.2f}] Valid:[{:.2f}] Test:[{:.2f}] | Update Test:[{:.2f}] at epoch:[{}]'
              .format(imp_num,  epoch, 
                                args.fix_epochs, 
                                epoch_loss, 
                                train_accuracy * 100,
                                valid_accuracy * 100,
                                test_accuracy * 100, 
                                results['final_test'] * 100,
                                results['epoch']))
    print("=" * 120)
    print("INFO final: IMP:[{}], Train:[{:.2f}]  Best Val:[{:.2f}] at epoch:[{}] | Final Test Acc:[{:.2f}] Adj:[{:.2f}%] Wei:[{:.2f}%]"
        .format(imp_num,    results['final_train'] * 100,
                            results['highest_valid'] * 100,
                            results['epoch'],
                            results['final_test'] * 100,
                            results['adj_spar'],
                            results['wei_spar']))
    print("=" * 120)


def main_get_mask(args, imp_num, rewind_weight_mask=None, resume_train_ckpt=None):

    device = torch.device("cuda:" + str(args.device))
    dataset = PygNodePropPredDataset(name=args.dataset)
    data = dataset[0]
    split_idx = dataset.get_idx_split()
    evaluator = Evaluator(args.dataset)

    x = data.x.to(device)
    y_true = data.y.to(device)
    train_idx = split_idx['train'].to(device)

    edge_index = data.edge_index.to(device)
    edge_index = to_undirected(edge_index, data.num_nodes)

    if args.self_loop:
        edge_index = add_self_loops(edge_index, num_nodes=data.num_nodes)[0]

    args.in_channels = data.x.size(-1)
    args.num_tasks = dataset.num_classes

    print("-" * 120)
    model = DeeperGCN(args).to(device)
    pruning.add_mask(model, args.num_layers)
    
    if rewind_weight_mask:
        model.load_state_dict(rewind_weight_mask)
        adj_spar, wei_spar = pruning.print_sparsity(model, args)

    pruning.add_trainable_mask_noise(model, args, c=1e-5)

    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    results = {'highest_valid': 0,'final_train': 0, 'final_test': 0, 'highest_train': 0, 'epoch':0}
    
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

    for epoch in range(start_epoch, args.mask_epochs + 1):
        
        epoch_loss = train(model, x, edge_index, y_true, train_idx, optimizer, args)
        result = test(model, x, edge_index, y_true, split_idx, evaluator)
        train_accuracy, valid_accuracy, test_accuracy = result

        if valid_accuracy > results['highest_valid']:
            results['highest_valid'] = valid_accuracy
            results['final_train'] = train_accuracy
            results['final_test'] = test_accuracy
            results['epoch'] = epoch
            rewind_weight_mask, adj_spar, wei_spar = pruning.get_final_mask_epoch(model, rewind_weight_mask, args)
            #pruning.save_all(model, rewind_weight_mask, optimizer, imp_num, epoch, args.model_save_path, 'IMP{}_train_ckpt'.format(imp_num))

        print(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()) + ' | ' +
              'IMP:[{}] (GET Mask) Epoch:[{}/{}]\t LOSS:[{:.4f}] Train :[{:.2f}] Valid:[{:.2f}] Test:[{:.2f}] | Update Test:[{:.2f}] at epoch:[{}] | Adj:[{:.2f}%] Wei:[{:.2f}%]'
              .format(imp_num,  epoch, 
                                args.mask_epochs, 
                                epoch_loss, 
                                train_accuracy * 100,
                                valid_accuracy * 100,
                                test_accuracy * 100,
                                results['final_test'] * 100,
                                results['epoch'],
                                adj_spar, 
                                wei_spar))
    print('-' * 100)
    print("INFO : IMP:[{}] (GET MASK) Final Result Train:[{:.2f}]  Valid:[{:.2f}]  Test:[{:.2f}] | Adj:[{:.2f}%] Wei:[{:.2f}%] "
        .format(imp_num, results['final_train'] * 100,
                         results['highest_valid'] * 100,
                         results['final_test'] * 100,
                         adj_spar, 
                         wei_spar))
    print('-' * 100)
    return rewind_weight_mask


if __name__ == "__main__":

    args = ArgsInit().save_exp()
    
    pruning.print_args(args, 120)

    start_imp = 1
    rewind_weight_mask = None
    resume_train_ckpt = None

    if args.resume_dir:
        resume_train_ckpt = torch.load(args.resume_dir)
        start_imp = resume_train_ckpt['imp_num']
        rewind_weight_mask = resume_train_ckpt['rewind_weight_mask']

        if 'fixed_ckpt' in args.resume_dir:
            main_fixed_mask(args, start_imp, rewind_weight_mask, resume_train_ckpt)
            start_imp += 1

    for imp_num in range(start_imp, 21):

        rewind_weight_mask = main_get_mask(args, imp_num, rewind_weight_mask, resume_train_ckpt)
        main_fixed_mask(args, imp_num, rewind_weight_mask)

        
