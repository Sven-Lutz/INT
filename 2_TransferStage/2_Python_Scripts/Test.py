import asyncio
from bleak import BleakClient

async def run(address, loop):
  async with BleakClient(address, loop=loop) as client:
     await client.connect()
     services = await client.get_services()
     for service in services:
         characteristics = await client.get_characteristics(service.handle)
         for characteristic in characteristics:
             await client.read_characteristic(characteristic.handle)
             await client.write_characteristic(characteristic.handle, b'Hello World')

loop = asyncio.get_event_loop()
loop.run_until_complete(run('CA:D4:DB:59:29:A0', loop))