# TableTap engineering rules

Follow [Ponytail](https://github.com/DietrichGebert/ponytail) (full mode):
the smallest complete change beats new abstraction. Read the affected
callers and preserve validation, hardware safety, and error handling.
Prefer existing libraries and standard-library features to new dependencies.
Do not add a feature without a real user problem. Every nontrivial
decision or regression fix needs a focused automated test.
Do not claim synthetic microphone tests prove real-world acoustic accuracy.
Remove unused code only after checking every caller. Review the full
changed call path before merging; CI must pass.
