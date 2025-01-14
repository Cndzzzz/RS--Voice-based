import os
import numpy as np
import pandas as pd
from tqdm import tqdm

import torch
import torch.nn as nn
import torch.optim as optim
import torch.backends.cudnn as cudnn
#from daisy.utils.config import model_config, initializer_config, optimizer_config

class PointFM(nn.Module):
    def __init__(self, 
                 user_num, 
                 item_num, 
                 factors=84, 
                 epochs=20, 
                 lr=0.001,
                 reg_1 = 0.001,
                 reg_2 = 0.001,
                 loss_type='CL',
                 optimizer='sgd',
                 initializer='normal',
                 gpuid='0', 
                 feature=1,
                 early_stop=True):
        """
        Point-wise FM Recommender Class
        Parameters
        ----------
        user_num : int, the number of users
        item_num : int, the number of items
        factors : int, the number of latent factor
        epochs : int, number of training epochs
        lr : float, learning rate
        reg_1 : float, first-order regularization term
        reg_2 : float, second-order regularization term
        loss_type : str, loss function type
        optimizer : str, optimization method for training the algorithms
        initializer: str, parameter initializer
        gpuid : str, GPU ID
        early_stop : bool, whether to activate early stop mechanism

        """
        super(PointFM, self).__init__()

        os.environ['CUDA_VISIBLE_DEVICES'] = gpuid
        cudnn.benchmark = True

        self.epochs = epochs
        self.lr = lr
        self.reg_1 = reg_1
        self.reg_2 = reg_2
        self.feature = feature

        self.embed_user = nn.Embedding(user_num, factors)
        self.embed_item = nn.Embedding(item_num, factors)

        self.u_bias = nn.Embedding(user_num, 1)
        self.i_bias = nn.Embedding(item_num, 1)

        if self.feature == 0:
            self.embed_gender = nn.Embedding(2, factors)
            self.g_bias = nn.Embedding(2, 1)
        elif self.feature == 1:
            self.embed_age = nn.Embedding(3, factors)
            self.a_bias = nn.Embedding(3, 1)
        elif self.feature == 2:
            self.embed_gender = nn.Embedding(2, factors)
            self.g_bias = nn.Embedding(2, 1)
            self.embed_age = nn.Embedding(3, factors)
            self.a_bias = nn.Embedding(3, 1)

        self.bias_ = nn.Parameter(torch.tensor([0.0]))

        # init weight
        nn.init.normal_(self.embed_user.weight)
        nn.init.normal_(self.embed_item.weight)
        if self.feature == 0:
            nn.init.normal_(self.embed_gender.weight)
            nn.init.constant_(self.g_bias.weight, 0.0)
        elif self.feature == 1:
            nn.init.normal_(self.embed_age.weight)
            nn.init.constant_(self.a_bias.weight, 0.0)
        elif self.feature == 2:
            nn.init.normal_(self.embed_gender.weight)
            nn.init.constant_(self.g_bias.weight, 0.0)
            nn.init.normal_(self.embed_age.weight)
            nn.init.constant_(self.a_bias.weight, 0.0)


        nn.init.constant_(self.u_bias.weight, 0.0)
        nn.init.constant_(self.i_bias.weight, 0.0)

        self.loss_type = loss_type
        self.optimizer = optimizer
        self.early_stop = early_stop

    def forward(self, user, item, gender=None, age=None):
        embed_user = self.embed_user(user)
        embed_item = self.embed_item(item)

        pred = (embed_user * embed_item).sum(dim=-1, keepdim=True)
        pred += self.u_bias(user) + self.i_bias(item) + self.bias_
        if self.feature == 0:
            embed_gender = self.embed_gender(gender)
            pred += (embed_gender * embed_user).sum(dim=-1, keepdim=True) + (embed_gender * embed_item).sum(dim=-1, keepdim=True)
            pred += self.g_bias(gender)
        elif self.feature == 1:
            embed_age = self.embed_age(age)
            pred += (embed_age * embed_user).sum(dim=-1, keepdim=True) + (embed_age * embed_item).sum(dim=-1, keepdim=True)
            pred += self.a_bias(age)
        elif self.feature == 2:
            embed_gender = self.embed_gender(gender)
            embed_age = self.embed_age(age)
            pred += (embed_gender * embed_user).sum(dim=-1, keepdim=True) + (embed_gender * embed_item).sum(dim=-1, keepdim=True)
            pred += (embed_age * embed_user).sum(dim=-1, keepdim=True) + (embed_age * embed_item).sum(dim=-1, keepdim=True)
            pred += (embed_age * embed_gender).sum(dim=-1, keepdim=True)
            pred += self.g_bias(gender) + self.a_bias(age)

        return pred.view(-1)

    def fit(self, train_loader):
        if torch.cuda.is_available():
            self.cuda()
        else:
            self.cpu()

        optimizer = optim.SGD(self.parameters(), lr=self.lr)

        if self.loss_type == 'CL':
            criterion = nn.BCEWithLogitsLoss(reduction='sum')
        elif self.loss_type == 'SL':
            criterion = nn.MSELoss(reduction='sum')
        else:
            raise ValueError(f'Invalid loss type: {self.loss_type}')

        last_loss = 0.
        for epoch in range(1, self.epochs + 1):
            self.train()

            current_loss = 0.
            # set process bar display
            pbar = tqdm(train_loader)
            pbar.set_description(f'[Epoch {epoch:03d}]')
            for user, item, gender, age, label in pbar:
                user = user.cuda()
                item = item.cuda()
                label = label.cuda()
                if self.feature == 0:
                    gender = gender.cuda()
                elif self.feature == 1:
                    age = age.cuda()
                elif self.feature == 2:
                    gender = gender.cuda()
                    age = age.cuda()

                self.zero_grad()
                if self.feature == 0:
                    prediction = self.forward(user, item, gender=gender)
                elif self.feature == 1:
                    prediction = self.forward(user, item, age=age)
                elif self.feature == 2:
                    prediction = self.forward(user, item, gender=gender, age=age)
                else:
                    prediction = self.forward(user, item)

                loss = criterion(prediction, label)
                loss += self.reg_1 * (self.embed_item.weight.norm(p=1) + self.embed_user.weight.norm(p=1))
                loss += self.reg_2 * (self.embed_item.weight.norm() + self.embed_user.weight.norm())

                if self.feature == 0:
                    loss += self.reg_1 * (self.embed_gender.weight.norm(p=1))
                    loss += self.reg_2 * (self.embed_gender.weight.norm())
                elif self.feature == 1:
                    loss += self.reg_1 * (self.embed_age.weight.norm(p=1))
                    loss += self.reg_2 * (self.embed_age.weight.norm())
                elif self.feature == 2:
                    loss += self.reg_1 * (self.embed_gender.weight.norm(p=1) + self.embed_age.weight.norm(p=1))
                    loss += self.reg_2 * (self.embed_gender.weight.norm() + self.embed_age.weight.norm())

                if torch.isnan(loss):
                    raise ValueError(f'Loss=Nan or Infinity: current settings does not fit the recommender')

                loss.backward()
                optimizer.step()

                pbar.set_postfix(loss=loss.item())
                current_loss += loss.item()

            self.eval()
            delta_loss = float(current_loss - last_loss)
            if (abs(delta_loss) < 1e-5) and self.early_stop:
                print('Satisfy early stop mechanism')
                break
            else:
                last_loss = current_loss

    def predict(self, u, i, g=None, a=None):
        if self.feature == 0:
            pred = self.forward(u, i, gender=g).cpu()
        elif self.feature == 1:
            pred = self.forward(u, i, age=a).cpu()
        elif self.feature == 2:
            pred = self.forward(u, i, gender=g, age=a).cpu()
        else:
            pred = self.forward(u, i).cpu()
        
        return pred
