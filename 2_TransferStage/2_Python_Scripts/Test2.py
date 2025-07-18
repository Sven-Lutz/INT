import os

from Configurator import WritingManager

project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

writer = WritingManager(project)

temp,_ = writer.read_yaml("temp")
print(temp)
print(temp.get("Remaining PVA Time","N/A"))
print(type(temp))