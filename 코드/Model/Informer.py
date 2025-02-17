import torch
import torch.nn as nn
import torch.nn.functional as F
import math
import numpy as np

class ProbAttention(nn.Module):
    def __init__(self, mask_flag=True, factor=5, scale=None, attention_dropout=0.1):
        super(ProbAttention, self).__init__()
        self.factor = factor
        self.scale = scale
        self.mask_flag = mask_flag
        self.dropout = nn.Dropout(attention_dropout)

    def forward(self, queries, keys, values, attn_mask):
        if queries.dim() == 2:
            queries = queries.unsqueeze(0)
        if keys.dim() == 2:
            keys = keys.unsqueeze(0)
        if values.dim() == 2:
            values = values.unsqueeze(0)

        B, L, E = queries.shape
        _, S, _ = keys.shape
        
        scale = self.scale or 1./math.sqrt(E)
        scores = torch.matmul(queries, keys.transpose(1, 2))
        
        if self.mask_flag:
            if attn_mask is None:
                attn_mask = torch.triu(torch.ones(L, S), diagonal=1).bool().to(queries.device)
            scores.masked_fill_(attn_mask, -np.inf)
        
        scores = scale * scores
        attn = self.dropout(torch.softmax(scores, dim=-1))
        context = torch.matmul(attn, values)
        
        return context

class EncoderLayer(nn.Module):
    def __init__(self, attention, emb_dim, d_ff=None, dropout=0.1, activation="relu"):
        super(EncoderLayer, self).__init__()
        d_ff = d_ff or 4*emb_dim
        self.attention = attention
        self.conv1 = nn.Conv1d(in_channels=emb_dim, out_channels=d_ff, kernel_size=1)
        self.conv2 = nn.Conv1d(in_channels=d_ff, out_channels=emb_dim, kernel_size=1)
        self.norm1 = nn.LayerNorm(emb_dim)
        self.norm2 = nn.LayerNorm(emb_dim)
        self.dropout = nn.Dropout(dropout)
        self.activation = F.relu if activation == "relu" else F.gelu

    def forward(self, x, attn_mask=None):
        new_x = self.attention(x, x, x, attn_mask)
        x = x + self.dropout(new_x)
        x = self.norm1(x)
        y = x
        y = self.dropout(self.activation(self.conv1(y.transpose(-1,1))))
        y = self.dropout(self.conv2(y).transpose(-1,1))
        return self.norm2(x+y)

class Encoder(nn.Module):
    def __init__(self, attn_layers, norm_layer=None):
        super(Encoder, self).__init__()
        self.attn_layers = nn.ModuleList(attn_layers)
        self.norm = norm_layer

    def forward(self, x, attn_mask=None):
        for attn_layer in self.attn_layers:
            x = attn_layer(x, attn_mask=attn_mask)
        if self.norm is not None:
            x = self.norm(x)
        return x

class Informer(nn.Module):
    def __init__(self, enc_in,seq_len, 
                  out_dim=1, factor=5, emb_dim=1024, n_heads=8, e_layers=3, 
                 dropout=0.0, activation='gelu'):
        super(Informer, self).__init__()
        self.seq_len = seq_len
        self.emb_dim = emb_dim

        # Encoding
        self.enc_embedding = nn.Linear(enc_in, emb_dim)
        
        # Attention
        self.encoder = Encoder(
            [
                EncoderLayer(
                    ProbAttention(False, factor, attention_dropout=dropout), 
                    emb_dim, emb_dim * 4, dropout=dropout, activation=activation
                ) for _ in range(e_layers)
            ],
            norm_layer=torch.nn.LayerNorm(emb_dim)
        )
        
        # Decoder (2D output projection)
        self.projection = nn.Linear(emb_dim, out_dim, bias=True) 
        
    def forward(self, x_enc):
        enc_out = self.enc_embedding(x_enc)
        enc_out = self.encoder(enc_out)
        
        hidden = enc_out[:, -1, :]  # (batch_size, emb_dim)

        dec_out = self.projection(hidden)  # (batch_size, output_dim)
        
        return dec_out, hidden
