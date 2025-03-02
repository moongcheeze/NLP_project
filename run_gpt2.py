import os

from typing import Dict

from contextlib import contextmanager
from tqdm import tqdm
import argparse
import numpy as np
import torch
from torch.utils.data import Dataset
from torch.utils.data import DataLoader

from models.gpt2 import GPT2LM
from models.gpt2_prefetch.py import PrefetchGPT2LM
from utils import event_measure

import time
 
os.environ["CUDA_VISIBLE_DEVICES"]="0"

cfgs: Dict[str, Dict[str, int]] = {
    'gpt2_small': {'embed_dim': 768, 'num_heads': 12, 'num_layers': 12},
    'gpt2_medium': {'embed_dim': 1024, 'num_heads': 16, 'num_layers': 24},
    'gpt2_large': {'embed_dim': 1280, 'num_heads': 20, 'num_layers': 36},
    'gpt2_xl': {'embed_dim': 1600, 'num_heads': 25, 'num_layers': 48},
    'gpt3_6.7b': {'embed_dim': 4096, 'num_heads': 32, 'num_layers': 32},
    'gpt3_13b': {'embed_dim': 5200, 'num_heads': 40, 'num_layers': 40},
    'gpt3_175b': {'embed_dim': 12288, 'num_heads': 96, 'num_layers': 96},
}


class MockDataset(Dataset):
    def __init__(self, dsize, seq_len=1024):
        self.dsize = dsize
        self.data = []
        for i in range(dsize):
            self.data.append(torch.randint(low=0, high=50256, size=(seq_len,)))

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        d = self.data[idx]
        return d


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', type=str, default='gpt2_xl',
                        const='gpt2_xl', nargs='?',
                        choices=['gpt2_small', 'gpt2_medium', 'gpt2_large', 'gpt2_xl',
                                 'gpt3_6.7b', 'gpt3_13b', 'gpt3_175b'],
                        help='model type')
    parser.add_argument('--enable-prefetch', action='store_true',
                        help='whether to enable prefetch optimization')
    parser.add_argument('--enable-cudnn-benchmark', action='store_true',
                        help='whether to enable cudnn benchmark option')
    parser.add_argument('--num-streams', type=int, default=3, help='# of prefetch streams')
    parser.add_argument('--warmups', type=int, default=2, help='# of warm up steps')
    return parser.parse_args()


def main():
    torch.cuda.set_device(0)

    #device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

    #print('Device:', device)  
    #print('Count of using GPUs:', torch.cuda.device_count())   
    #print('Current cuda device:', torch.cuda.current_device())
    
    start = time.time()

    args = get_args()
    print("###############################")
    print("#           configs           #")
    print("###############################")
    print(vars(args))

    model_config = cfgs[args.model]

    if args.enable_cudnn_benchmark:
        torch.backends.cudnn.benchmark = True
    
    if args.enable_prefetch:
        model_config['num_prefetch_streams'] = args.num_streams
        #model = torch.nn.parallel.DistributedDataParallel(PrefetchGPT2LM(**model_config), device_ids=[0, 1]).eval().cuda()
        model = PrefetchGPT2LM(**model_config).eval().cuda()
    else:
        model = GPT2LM(**model_config).eval().cuda()
        #model = torch.nn.parallel.DistributedDataParallel(GPT2LM(**model_config), device_ids=[0, 1]).eval().cuda()
        #model=torch.nn.DataParallel(GPT2LM(**model_config), device_ids=[0,1]).eval()
        #model.cuda()
        #device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        #model.to(device)

    num_warmup = args.warmups
    SEQ_LEN = 1024
    synthetic_dataset = MockDataset(3 + num_warmup, SEQ_LEN)
    dataloader = DataLoader(synthetic_dataset, batch_size=1, shuffle=False)

    fw_times = []
    for step, inp in enumerate(tqdm(dataloader)):
        if step < num_warmup:
            out = model(inp.cuda())
        else:
            with torch.no_grad(), event_measure() as result:
                out = model(inp.cuda())
            fw_times.append(result['time'])

    end = time.time()

    avg_fw_time = np.mean(fw_times)
    avg_throughput = SEQ_LEN / (avg_fw_time / 1000)
    execution_time = end - start
    #print(f"Avg. step time: {avg_fw_time} ms \tAvg. throughput: {avg_throughput} tokens/sec \tExecution Time: {execution_time} sec")
    print(f"Avg. throughput: {avg_throughput} tokens/sec")


if __name__ == '__main__':
    main()
