# Safety Notes

tenra Partition is not production-safe partitioning software. The current implementation is a read-only visualizer, operation planner, simulator, and integrated lab harness.

The safety validator currently detects:

- Unknown or unsupported filesystem type
- Mounted partitions
- Encrypted or BitLocker-placeholder partitions
- Dirty filesystem placeholder
- Insufficient shrinkable free space
- Non-adjacent source and target partitions
- Unsupported partition table type
- Alignment issues
- Unsupported movement or resize operations

Blocking findings refuse the operation plan. Even when the plan is ready, execution remains disabled.
