
import rly02 as smartPlug
import time
smartPlug.turn_relay_1_on()
smartPlug.turn_relay_2_on()

time.sleep(2)

smartPlug.turn_relay_1_off()
smartPlug.turn_relay_2_off()
