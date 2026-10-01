**Issue:** Support tickets are being assigned due dates that fall on company holidays, creating confusion and burnout.

**Details:**

A customer ticket was created on Tuesday, Feb 20, 2024. Per SLA policy, it should be due 2 business days later. Our system calculated the due date as 2024-02-22 (Thursday), but that's a company holiday (town hall day). Finance and support teams expect the due date to be 2024-02-23 (Friday).

**What to fix:**

Update `sla.py` to correctly calculate SLA due dates by skipping company holidays in addition to weekends. The list of company holidays is maintained in `holidays.json`.

Make sure the fix correctly handles the test case above: a ticket created on Feb 20 with a 2-business-day SLA should be due on Feb 23, not Feb 22.
