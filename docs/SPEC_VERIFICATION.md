# Component Specification Verification

This document describes the automated verification system that prevents incorrect component specifications from being committed.

## Problem

Component specs in `backend/calculator.py` are manually entered and can contain errors (e.g., wrong channel count, VIN range, current ratings). Previously, these errors went unnoticed until they caused issues in generated designs.

## Solution

An automated verification script (`backend/verify_specs.py`) that:

1. **Extracts data from datasheet PDFs** - Reads the first 3 pages of each datasheet
2. **Compares against COMPONENT_SPECS** - Checks for obvious errors
3. **Flags mismatches** - Prevents commits with specification errors

## Running Verification Manually

```bash
python backend/verify_specs.py
```

## Pre-commit Hook

A pre-commit hook is installed in `.git/hooks/pre-commit` that automatically runs verification when:
- `backend/calculator.py` is modified
- Files in `datasheets/` are added/modified

If verification fails, the commit is blocked with an error message.

### To Skip Verification (Not Recommended)

```bash
git commit --no-verify -m "your message"
```

## Adding New Components

When adding a new component to `COMPONENT_SPECS`:

1. **Single-output parts** - No changes needed to verification script
2. **Multi-output parts** - Add to `KNOWN_MULTI_OUTPUT` dictionary:
   ```python
   KNOWN_MULTI_OUTPUT = {
       'LTM4671': 4,   # Quad output
       'LTM4675': 2,   # Dual output
       # Add new multi-output parts here
   }
   ```

3. **Run verification** - Ensure no issues are reported:
   ```bash
   python backend/verify_specs.py
   ```

## Verification Checks

### Channel Count
- **Known multi-output parts**: Verified against `KNOWN_MULTI_OUTPUT`
- **Unknown parts**: Defaults to 1 channel (safe assumption)

### VIN Range
- Checks if spec min is lower than datasheet minimum
- Checks if spec max is higher than datasheet maximum

### Current Rating
- Checks if spec current exceeds datasheet maximum by more than 50%

## Known Limitations

- PDF text extraction may not work perfectly for all datasheets
- Some checks fall back to "manual verification recommended"
- The hook only runs when relevant files are modified
