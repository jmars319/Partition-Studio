# Target Workflow

The target problem starts with this layout:

```text
[C: NTFS, nearly full][E: NTFS, large amount of free space]
```

The desired result is:

```text
[C: NTFS, larger][E: NTFS, smaller and moved right]
```

The modeled operation queue is:

1. Validate disk.
2. Validate E has enough free space.
3. Shrink E filesystem.
4. Shrink E partition.
5. Move E right.
6. Expand C partition.
7. Expand C filesystem.
8. Verify result.

Windows Disk Management cannot directly solve this layout when the only available capacity is free space inside E. Shrinking E creates unallocated space after E. C can only grow into unallocated space immediately after C. Moving E right is what makes that unallocated space adjacent to C.

The planner models the final geometry as:

- C start sector stays the same.
- C end sector increases by the requested amount.
- E start sector increases by the requested amount.
- E end sector stays the same.
- E size shrinks by the requested amount.
