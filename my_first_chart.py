import matplotlib.pyplot as plt
plt.rcParams['font.family'] = 'Malgun Gothic'

temp = [14, 13, 10, 14, 9, 4, 5]
fig, ax = plt.subplots(figsize = (7, 4))
ax.plot(temp)
for i , p in enumerate(temp):
    ax.annotate(f"{p:,}", (i, p), textcoords= "offset points", xytext = (0, 8), ha = "center")
ax.set_title("내 첫 그래프")
fig.savefig("my_first_chart.png")