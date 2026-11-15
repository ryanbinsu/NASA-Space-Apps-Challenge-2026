import glob
import numpy as np
import matplotlib.pyplot as plt
from astropy.io import fits

files = sorted(glob.glob("spherex_output/Barnard*/*/IMAGE.fits"))
n = len(files)
cols = min(5, n)
rows = (n + cols - 1) // cols
fig, axes = plt.subplots(rows, cols, figsize=(4*cols, 4*rows))
axes = np.array(axes).reshape(-1)
for i, f in enumerate(files):
    data = fits.open(f)[1].data.astype(float)
    vmin, vmax = np.nanpercentile(data, [1, 99])
    axes[i].imshow(data, cmap="gray", vmin=vmin, vmax=vmax, origin="lower")
    axes[i].set_title(f.split('/')[-2], fontsize=8)
    axes[i].axis("off")
for j in range(len(files), len(axes)):
    axes[j].axis("off")
plt.suptitle("SPHEREx: Barnard's Star — 10 Real Exposures", fontsize=16, fontweight="bold")
plt.tight_layout()
plt.savefig("barnard_grid.png", dpi=150, bbox_inches="tight")
