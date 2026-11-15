import sys
import numpy as np
import matplotlib.pyplot as plt
from astropy.io import fits

files = sys.argv[1:]
fig, axes = plt.subplots(1, len(files), figsize=(5*len(files), 5))
if len(files) == 1:
    axes = [axes]
for ax, f in zip(axes, files):
    data = fits.open(f)[1].data.astype(float)
    vmin, vmax = np.nanpercentile(data, [1, 99])
    ax.imshow(data, cmap="gray", vmin=vmin, vmax=vmax, origin="lower")
    ax.set_title(f.split('/')[-2])
    ax.axis("off")
plt.tight_layout()
plt.savefig("comparison.png", dpi=150, bbox_inches="tight")
print("Saved comparison.png")
