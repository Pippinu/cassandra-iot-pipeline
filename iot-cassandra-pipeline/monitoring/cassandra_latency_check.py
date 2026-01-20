import time
from cassandra.cluster import Cluster
from cassandra import ConsistencyLevel

cluster = Cluster(['127.0.0.1'])
session = cluster.connect('iot_analytics')

def test_latency(cl_name, cl_value):
    session.default_consistency_level = cl_value
    start = time.perf_counter()
    
    # Using a real query
    session.execute("SELECT * FROM sensor_events WHERE device_id = ad618d2c-192c-4bed-bdff-cb3c33cdc7c5 LIMIT 100;")
    
    end = time.perf_counter()
    print(f"Consistency {cl_name}: {(end - start) * 1000:.2f} ms")

test_latency("ONE", ConsistencyLevel.ONE)
test_latency("QUORUM", ConsistencyLevel.QUORUM)
test_latency("ALL", ConsistencyLevel.ALL)