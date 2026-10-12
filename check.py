import pandas as pd
import matplotlib.pyplot as plt

watchlist_df = pd.read_csv('watchlist.csv')
print(watchlist_df["code"].tolist())        #[5930, 660, 5380]

watchlist_df = pd.read_csv("watchlist.csv", dtype = {"code": str})
print(watchlist_df["code"].tolist())        #['005930', '000660', '005380']

dic = dict(zip(watchlist_df["code"], watchlist_df["name"]))
print(dic)



