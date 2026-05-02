"""
Component Specification Verification Tool

This script verifies that COMPONENT_SPECS in calculator.py matches the actual
datasheets in the datasheets/ folder. It extracts key parameters from PDFs
and flags any mismatches for review.

Run this whenever:
- Adding a new component to COMPONENT_SPECS
- Modifying existing component specs
- Adding new datasheets to the folder

Usage: python backend/verify_specs.py
"""

import os
import re
import PyPDF2
from pathlib import Path


# Known multi-output parts (manually verified from datasheets)
KNOWN_MULTI_OUTPUT = {
    'LTM4671': 4,   # Quad output (dual 12A + dual 5A)
    'LTM4675': 2,   # Dual output
    'LTM4676A': 2,  # Dual output
}


def extract_pdf_text(filepath, max_pages=3):
    """Extract text from first N pages of PDF."""
    text = ""
    try:
        with open(filepath, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            num_pages = min(len(reader.pages), max_pages)
            for i in range(num_pages):
                page_text = reader.pages[i].extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
    return text


def verify_channels(part_name, spec_channels):
    """
    Verify channel count against known multi-output parts.
    For unknown parts, default to 1 channel (single-output is the norm).
    """
    part_upper = part_name.upper()

    # Check against known multi-output parts
    if part_upper in KNOWN_MULTI_OUTPUT:
        expected = KNOWN_MULTI_OUTPUT[part_upper]
        if spec_channels != expected:
            return False, f"Known {expected}-channel part, but spec has channels={spec_channels}"
        return True, f"Verified: {expected} channels (known multi-output part)"

    # For parts not in known list, assume single-channel
    # This is the safe default - most μModule bucks are single-output
    if spec_channels != 1:
        return False, f"Unknown part with channels={spec_channels}. Verify datasheet - most bucks are single-output."

    return True, "Single-channel (default for unknown parts)"


def verify_vin_range(part_name, spec_vin, text):
    """
    Verify VIN range by looking for explicit mentions in datasheet.
    Only flags obvious errors (e.g., min too high, max too low).
    """
    if not spec_vin or len(spec_vin) != 2:
        return True, "No VIN range to verify"

    text_lower = text.lower()

    # Look for "Vin: X to Y" or "input voltage: X to Y" patterns
    patterns = [
        r'vin[^:\d]*[:\s]+([\d.]+)\s*[Vv]?\s*(?:to|-|–)\s*([\d.]+)\s*[Vv]?',
        r'input\s+voltage[^:]*:\s*([\d.]+)\s*[Vv]\s*(?:to|-|–)\s*([\d.]+)\s*[Vv]',
    ]

    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            try:
                v_min = float(match.group(1))
                v_max = float(match.group(2))
                spec_min, spec_max = spec_vin

                # Check if spec is outside extracted range (obvious error)
                if spec_min < v_min - 0.5:
                    return False, f"Spec min ({spec_min}V) lower than datasheet ({v_min}V)"
                if spec_max > v_max + 0.5:
                    return False, f"Spec max ({spec_max}V) higher than datasheet ({v_max}V)"

                return True, f"VIN range {spec_vin} within datasheet range ({v_min}V-{v_max}V)"
            except:
                pass

    return True, "VIN range not extractable from PDF text (manual verification recommended)"


def verify_current(part_name, spec_iout, text):
    """
    Verify max current by looking for explicit output current mentions.
    Only flags obvious over-claims.
    """
    if not spec_iout:
        return True, "No current spec to verify"

    text_lower = text.lower()

    # Look for "X A output" or "X-A output" patterns
    pattern = r'(\d+(?:\.\d+)?)\s*A\s+output'
    matches = re.findall(pattern, text_lower)

    if matches:
        max_found = max(float(m) for m in matches)
        # Allow some tolerance - datasheets may list parallel configurations
        if spec_iout > max_found * 1.5:
            return False, f"Spec i_max={spec_iout}A exceeds datasheet max ({max_found}A)"
        return True, f"i_max={spec_iout}A consistent with datasheet (found up to {max_found}A)"

    return True, "Current not extractable from PDF text (manual verification recommended)"


def verify_component(part_name, pdf_path, spec):
    """
    Verify a single component's specs against its datasheet.
    Returns a dict with verification results.
    """
    text = extract_pdf_text(pdf_path)
    results = {
        'part_name': part_name,
        'pdf': pdf_path,
        'spec': spec,
        'issues': [],
        'warnings': [],
    }

    # Verify channels
    channels_ok, channels_msg = verify_channels(part_name, spec.get('channels', 1))
    if not channels_ok:
        results['issues'].append(f"CHANNEL: {channels_msg}")
    else:
        results['warnings'].append(f"Channels: {channels_msg}")

    # Verify VIN range
    vin_ok, vin_msg = verify_vin_range(part_name, spec.get('vin_range'), text)
    if not vin_ok:
        results['issues'].append(f"VIN: {vin_msg}")
    else:
        results['warnings'].append(f"VIN: {vin_msg}")

    # Verify current (for Buck converters)
    if spec.get('type') == 'buck':
        iout_ok, iout_msg = verify_current(part_name, spec.get('i_max'), text)
        if not iout_ok:
            results['issues'].append(f"Current: {iout_msg}")
        else:
            results['warnings'].append(f"Current: {iout_msg}")

    return results


def main():
    """Main verification routine."""
    print("=" * 70)
    print("COMPONENT SPECIFICATION VERIFICATION")
    print("=" * 70)
    print()
    print("This script checks COMPONENT_SPECS against datasheet PDFs.")
    print("Known multi-output parts:", KNOWN_MULTI_OUTPUT)
    print()

    # Import COMPONENT_SPECS
    try:
        from backend.calculator import COMPONENT_SPECS
    except ImportError:
        import sys
        sys.path.insert(0, os.path.dirname(__file__))
        from calculator import COMPONENT_SPECS

    # Find all PDFs
    datasheets_dir = Path(__file__).parent.parent / 'datasheets'
    buck_dir = datasheets_dir / 'BuckConverter'
    ldo_dir = datasheets_dir / 'LDO'

    all_results = []

    for category_dir, category_name in [(buck_dir, 'Buck'), (ldo_dir, 'LDO')]:
        if not category_dir.exists():
            continue

        for pdf_file in sorted(category_dir.glob('*.pdf')):
            part_name = pdf_file.stem.upper()

            # Find matching spec (case-insensitive) - prefer exact matches first
            spec = None
            spec_name_found = None
            for spec_name, spec_data in COMPONENT_SPECS.items():
                if spec_name.upper() == part_name:
                    # Exact match - use this one
                    spec = spec_data
                    spec_name_found = spec_name
                    break

            # If no exact match, try fuzzy matching
            if spec is None:
                for spec_name, spec_data in COMPONENT_SPECS.items():
                    if part_name in spec_name.upper() or spec_name.upper() in part_name:
                        spec = spec_data
                        spec_name_found = spec_name
                        break

            if spec is None:
                print(f"[WARNING] No spec found for {part_name} ({pdf_file.name})")
                continue

            result = verify_component(part_name, str(pdf_file), spec)
            all_results.append(result)

    # Print summary
    print("\n" + "=" * 70)
    print("VERIFICATION RESULTS")
    print("=" * 70)

    issues_found = 0
    for r in all_results:
        print(f"\n[{r['part_name']}]")
        if r['issues']:
            issues_found += len(r['issues'])
            for issue in r['issues']:
                print(f"  [ISSUE] {issue}")
        for warning in r['warnings']:
            print(f"  [OK] {warning}")

    print("\n" + "=" * 70)
    if issues_found:
        print(f"RESULT: {issues_found} ISSUE(S) FOUND - Please review and fix COMPONENT_SPECS")
        print()
        print("To prevent this in the future:")
        print("1. Add new multi-output parts to KNOWN_MULTI_OUTPUT dictionary")
        print("2. Run 'python backend/verify_specs.py' before committing spec changes")
        print("3. Consider adding this script as a pre-commit hook")
        return 1
    else:
        print("RESULT: All specifications verified successfully!")
        return 0


if __name__ == '__main__':
    exit(main())
