import yaml

with open(r"U:\Masterarbeit\X_PelliKAn\2_TransferStage\4_Config\test.yaml", 'r') as df:  # Read the default file
    data = yaml.safe_load(df)
print(data)
print(data["Containers"])
print(data["Containers"]["1 Sample"])