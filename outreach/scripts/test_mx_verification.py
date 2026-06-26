#!/usr/bin/env python
"""Quick test of MX verification functions."""
from __future__ import annotations

import sys
from pathlib import Path

# Add parent dir to path so we can import the batch script
sys.path.insert(0, str(Path(__file__).parent))

try:
    import dns.resolver
    print("✓ dns.resolver import successful")
except ImportError as e:
    print(f"✗ Failed to import dns.resolver: {e}")
    print("  Install with: pip install dnspython>=2.4.0")
    sys.exit(1)

# Test the MX verification functions
test_cases = [
    ("gmail.com", True, "Valid domain"),
    ("microsoft.com", True, "Valid domain"),
    ("prospektlab.com", True, "Valid domain"),
    ("example.invalid", False, "Invalid/test domain"),
    ("mailinator.com", False, "Known disposable domain"),
    ("guerrillamail.com", False, "Known disposable domain"),
    ("tempmail.com", False, "Known disposable domain"),
]

# Import verification functions
try:
    # We need to load the functions from the batch script
    import importlib.util
    spec = importlib.util.spec_from_file_location("batch_script", Path(__file__).parent / "run_supabase_outreach_batch.py")
    batch_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(batch_module)
    
    has_valid_mx = batch_module._has_valid_mx
    is_disposable = batch_module._is_disposable_or_bad_domain
    is_deliverable = batch_module._is_email_deliverable
    print("✓ Batch script functions imported successfully")
except Exception as e:
    print(f"✗ Failed to import batch script functions: {e}")
    sys.exit(1)

print("\n--- Testing MX Verification ---")
passed = 0
failed = 0

for domain, should_have_mx, description in test_cases:
    email = f"test@{domain}"
    has_mx = has_valid_mx(domain)
    is_bad_domain = is_disposable(email)
    is_deliv = is_deliverable(email)
    
    # For disposable domains, we expect them to fail deliverability
    if domain in ("mailinator.com", "guerrillamail.com", "tempmail.com"):
        expected_result = False
    else:
        expected_result = should_have_mx
    
    status = "✓" if is_deliv == expected_result else "✗"
    print(f"{status} {email:40} | MX:{has_mx!s:5} | Disposable:{is_bad_domain!s:5} | Deliverable:{is_deliv!s:5} | {description}")
    
    if is_deliv == expected_result:
        passed += 1
    else:
        failed += 1

print(f"\n--- Results ---")
print(f"Passed: {passed}/{len(test_cases)}")
print(f"Failed: {failed}/{len(test_cases)}")

if failed == 0:
    print("\n✓ All tests passed! MX verification is working correctly.")
    sys.exit(0)
else:
    print(f"\n✗ {failed} test(s) failed!")
    sys.exit(1)
