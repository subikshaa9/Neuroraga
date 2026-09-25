from pathlib import Path 
import numpy as np
import h5py
import json
import pandas as pd

# File path
filename = Path(r"C:/Users/nurni/AppData/Roaming/Capsule Data v2/Sessions/64afd545-ee81-4607-1025-7c8a552bcffb/session.h5") # h5 file path 
datasets = []
dataset_names = []

# Open and process the HDF5 file
with h5py.File(filename, "r") as f:
    for df_key in f.keys():
        data = np.array(f[df_key])
        datasets.append(data)
        dataset_names.append(df_key)

        # Print metadata
        for attr_key in f[df_key].attrs.keys():
            value = f[df_key].attrs[attr_key]
            if isinstance(value, bytes):  # decode if needed
                value = json.loads(value.decode("utf-8"))
                print(f"{df_key} => {value}")
            else:
                print(f"{df_key} {attr_key} => {value}", "\n")

# Save datasets to CSV
output_folder = Path("C:/Users/nurni/AppData/Roaming/Capsule Data v2/Sessions/64afd545-ee81-4607-1025-7c8a552bcffb") 
output_folder.mkdir(exist_ok=True)

for data, name in zip(datasets, dataset_names):
    df = pd.DataFrame(data)
    csv_path = output_folder / f"{name}.csv"
    df.to_csv(csv_path, index=False)

print(f"All datasets saved to: {output_folder.resolve()}")