import propar
import time


# Replace with your actual serial port (e.g., "COM3" on Windows or "/dev/ttyUSB0" on Linux)
PORT = "COM5"

flow = propar.instrument(PORT)

#print(flow.id)
"""
params = [{'proc_nr':  33, 'parm_nr': 0, 'parm_type': propar.PP_TYPE_FLOAT}]
values = flow.read_parameters(params)
print(values)
"""

params = {"Unknown (Maybe also Flow)": {'proc_nr':  33, 'parm_nr': 0, 'parm_type': propar.PP_TYPE_FLOAT},
           "Volumne Flow": {'proc_nr':  33, 'parm_nr': 6, 'parm_type': propar.PP_TYPE_FLOAT},
           "Normal Flow": {'proc_nr':  33, 'parm_nr': 0, 'parm_type': propar.PP_TYPE_FLOAT},
           "Totalizer Value": {'proc_nr':  33, 'parm_nr': 0, 'parm_type': propar.PP_TYPE_FLOAT}}

# Note that this uses the read_parameters function.
for param,val in params.items():
    #print(param)
    #print(val)
    values = flow.read_parameters([val])
    print(f"{param}: {values[0]["data"]}")
    #print(values[0]["data"])
#for p in params:

    #values = flow.read_parameters(p)

    #for value in values:
        #print(value)


value = flow.db.get_all_parameters()

#for sublist in value:
    #print(sublist)

#{'dde_nr': 152, 'proc_nr': 33, 'parm_nr': 6, 'parm_type': 65, 'parm_name': 'Volume flow'}
#{'dde_nr': 151, 'proc_nr': 33, 'parm_nr': 5, 'parm_type': 65, 'parm_name': 'Normal volume flow'}
#{'dde_nr': 393, 'proc_nr': 104, 'parm_nr': 17, 'parm_type': 65, 'parm_name': 'Totalizer value'}
#{'dde_nr': 394, 'proc_nr': 104, 'parm_nr': 18, 'parm_type': 96, 'parm_name': 'Totalizer unit'}


