import matplotlib.pyplot as plt

# Your NEW collected data
distances = [0, 75, 150, 225, 300]
data_rates = [241.36, 77.86, 117.87, 38.86, 334.04]
packets = [69, 15, 241, 109, 69]

fig, ax1 = plt.subplots(figsize=(8, 5))

color = 'tab:blue'
ax1.set_xlabel('Tag Position from Carrier (cm)', fontsize=12)
ax1.set_ylabel('Data Rate (bps)', color=color, fontsize=12)
ax1.plot(distances, data_rates, marker='o', color=color, linewidth=2, label="Data Rate")
ax1.tick_params(axis='y', labelcolor=color)
ax1.set_xticks(distances)

ax2 = ax1.twinx()  
color = 'tab:red'
ax2.set_ylabel('Packets Received', color=color, fontsize=12)
ax2.plot(distances, packets, marker='s', linestyle='--', color=color, linewidth=2, label="Packets")
ax2.tick_params(axis='y', labelcolor=color)

plt.title("Baseline Performance: Indoor Multipath Effects on 3m Link")
fig.tight_layout()  
plt.grid(True, linestyle=':', alpha=0.7)
plt.savefig("summary_performance.pdf") 
plt.show()