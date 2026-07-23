## Summary

- What changed?
- Why does it matter?

## Validation

- [ ] `python3 scripts/validate_skill.py`
- [ ] `python3 -m compileall -q skills tests scripts`
- [ ] `python3 -m unittest discover -s tests -p 'test_*.py' -v`
- [ ] Manual behavior checklist completed or explicitly not applicable

## Safety

- [ ] The change remains read-only with respect to Chats, traces, and Context Trees.
- [ ] No real trace, passage, Chat export, evidence bundle, or generated report is committed.
- [ ] Authorization and coverage gaps fail closed.

## Notes

- Compatibility, installation, or follow-up considerations:
