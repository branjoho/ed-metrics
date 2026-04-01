import re
import os
import pdfplumber


class ParseError(Exception):
    pass


def _parse_float(s):
    """Convert a string like '3.47', '11.2%', '143' to float, or None."""
    if s is None:
        return None
    s = s.strip().rstrip('%')
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _parse_int(s):
    """Convert a string like '125' to int, or None."""
    if s is None:
        return None
    s = s.strip().replace(',', '')
    try:
        return int(s)
    except (ValueError, TypeError):
        return None



def _extract_month_year_from_filename(pdf_path):
    """
    Extract month/year from filenames like:
      '2_2026 - ED Provider Metrics.pdf'
      '01_2026 - ED Provider Metrics.pdf'
      '9_2025 - ED Provider Metrics.pdf'
    Returns (month, year) as ints, or (None, None).
    """
    basename = os.path.basename(pdf_path)
    m = re.match(r'^(\d{1,2})_(\d{4})', basename)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def _extract_month_year_from_text(pages):
    """
    Fallback: extract month/year from the date range on the throughput page.
    Looks for patterns like '[8/29/2025 - 9/29/2025]' and returns the end date's month/year.
    """
    text = pages[2] if len(pages) > 2 else ''
    # Date range pattern: [M/DD/YYYY - M/DD/YYYY]
    m = re.search(r'\[\d{1,2}/\d{2}/\d{4}\s*-\s*(\d{1,2})/\d{2}/(\d{4})\]', text)
    if m:
        return int(m.group(1)), int(m.group(2))
    # Also try bare end date after "End Date"
    m = re.search(r'End Date\s*\n(\d{1,2})/\d{2}/(\d{4})', text)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def _parse_shift_data(pts_page_text):
    """
    Parse per-shift pts/hour from page 5 'by Shift' section.

    PDF layout (pdfplumber text order):
      Peers               <- axis label — acts as a BOUNDARY between shift sections
      [me_value]          <- your value (may appear 1-2x, same value rounded differently)
      [peers_value]       <- peer median
      SHIFT NAME [optional inline percentile or value]
      [optional percentile line]
      Peers               <- next boundary

    Strategy:
      - Split text into per-shift windows using "Peers" lines as boundaries.
      - Within each window: last numeric = peers, second-to-last (if distinct) = me.
      - Percentile is found after the shift name.
      - Special: ORCA Eve peers appears after the shift name (no "Peers" line before
        the next section); handle by peeking at lines after the shift name.
    """
    m = re.search(r'Average New Patient Assignments Per Hour by Shift.*', pts_page_text, re.DOTALL)
    if not m:
        return []

    section = m.group(0)
    lines = [l.strip() for l in section.split('\n') if l.strip()]

    # Matches known shift name lines (bare or with trailing inline percentile/value)
    shift_name_re = re.compile(
        r'^(ED\s+\S[\w ]*?|ORCA\s+\w[\w ]*?|EDFT)'
        r'(?:\s+\d+(?:\.\d+)?%\s*Percentile|\s+[\d.]+)?$',
        re.IGNORECASE,
    )

    # Purely numeric line (one or two floats)
    num_line_re = re.compile(r'^([\d.]+)(?:\s+([\d.]+))?$')

    def is_peers_boundary(line):
        """A line that starts with 'Peers' (may have trailing content) is a boundary."""
        return re.match(r'^Peers', line, re.IGNORECASE) is not None

    results = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # --- Detect shift name line ---
        sm = shift_name_re.match(line)
        if not sm:
            i += 1
            continue

        shift_name = sm.group(1).strip()

        # Inline percentile on the shift name line (e.g. "ED WestEve 13% Percentile")
        pctile_inline = re.search(r'(\d+(?:\.\d+)?)%\s*Percentile', line)
        pctile = float(pctile_inline.group(1)) if pctile_inline else None

        # Inline numeric on shift name (e.g. "ORCA Day 1.9966")
        inline_num_m = re.search(r'\s+([\d.]+)$', line)
        inline_num = _parse_float(inline_num_m.group(1)) if inline_num_m else None

        # --- Collect numerics backward until a "Peers" boundary or section start ---
        pre_vals = []
        for j in range(i - 1, max(i - 8, -1), -1):
            if is_peers_boundary(lines[j]):
                break  # stop at the Peers axis label
            if shift_name_re.match(lines[j]):
                break  # stop at another shift name (e.g. after "ORCA Day 1.9966")
            nm = num_line_re.match(lines[j])
            if nm:
                v2 = _parse_float(nm.group(2)) if nm.group(2) else None
                v1 = _parse_float(nm.group(1))
                if v2 is not None:
                    pre_vals.insert(0, v2)
                pre_vals.insert(0, v1)

        # --- Percentile: inline or in next 4 lines ---
        if pctile is None:
            for j in range(i + 1, min(i + 5, len(lines))):
                pm = re.search(r'(\d+(?:\.\d+)?)%\s*Percentile', lines[j])
                if pm:
                    pctile = float(pm.group(1))
                    break

        # --- Determine peers / me ---
        peers = None
        me = None

        if inline_num is not None and not pre_vals:
            # e.g. "ORCA Day 1.9966" — inline value is peers (no me data)
            peers = inline_num
        elif pre_vals:
            peers = pre_vals[-1]
            # me is the second-to-last DISTINCT value
            for v in reversed(pre_vals[:-1]):
                if v != peers:
                    me = v
                    break

        # If peers still None (e.g. ORCA Eve where peers follows shift name),
        # peek forward for a lone numeric before the next boundary
        if peers is None and not inline_num:
            for j in range(i + 1, min(i + 5, len(lines))):
                if is_peers_boundary(lines[j]) or shift_name_re.match(lines[j]):
                    break
                if '%' in lines[j]:
                    continue
                after_nm = num_line_re.match(lines[j])
                if after_nm:
                    if me is None:
                        peers = _parse_float(after_nm.group(1))
                    else:
                        peers = _parse_float(after_nm.group(1))
                    break

        if me is not None or peers is not None:
            results.append({
                'shift': shift_name,
                'me': me,
                'peers': peers,
                'pctile': pctile,
            })

        i += 1

    return results


def _get_full_text(pdf_path):
    """Return concatenated text from all pages, or raise on open failure."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            pages = []
            for page in pdf.pages:
                text = page.extract_text() or ''
                pages.append(text)
            return pages
    except FileNotFoundError:
        raise
    except Exception as e:
        raise ParseError(f"Could not open PDF: {e}") from e


def parse_metrics(pdf_path: str) -> dict:
    """
    Parse an ED Provider Metrics PDF.
    Returns a dict of all metric fields (values may be None if not found).
    Raises ParseError if the file is not a recognized ED metrics PDF.
    """
    # This will raise FileNotFoundError (not ParseError) for missing files
    pages = _get_full_text(pdf_path)
    full_text = '\n'.join(pages)

    # Validate it's an ED metrics PDF
    if 'Attending Provider Metrics' not in full_text and \
       'ED Provider' not in full_text:
        raise ParseError("Not a recognized ED Provider Metrics PDF")

    # Also ensure the throughput page (page 3) is present
    throughput_text = pages[2] if len(pages) > 2 else ''
    summary_text = pages[6] if len(pages) > 6 else ''

    if not throughput_text and not summary_text:
        raise ParseError("PDF is missing expected metric pages")

    # ----------------------------------------------------------------
    # Month / year — filename first, PDF text as fallback
    # ----------------------------------------------------------------
    month, year = _extract_month_year_from_filename(pdf_path)
    if not month or not year:
        month, year = _extract_month_year_from_text(pages)

    # ----------------------------------------------------------------
    # Patients — from admission rate fraction "(14/125)" on page 3 or 7
    # ----------------------------------------------------------------
    patients = None
    # Page 3 pattern: "11.2%\n11.2% 17.6%\n(14/125)"
    m = re.search(r'\((\d+)/(\d+)\)\s*\n.*?(?:Peers|Peer)', throughput_text)
    if not m:
        # Try simpler: find first fraction in admission rate section
        m = re.search(r'Admission Rate.*?\((\d+)/(\d+)\)', throughput_text, re.DOTALL)
    if m:
        patients = _parse_int(m.group(2))

    # ----------------------------------------------------------------
    # Parse page 3 (throughput) - primary source for me/peers/pctile
    # ----------------------------------------------------------------

    # Helper: extract a block like:
    #   "3.467289720 3.47\n3.8\n13% Percentile"
    # Returns (me_str, peers_str, pctile_str)

    # ---- Discharge LOS (Average) ----
    # Pattern: long float  short_float\npeers_float\npctile% Percentile
    discharge_los_me = None
    discharge_los_peers = None
    discharge_los_pctile = None

    m = re.search(
        r'Average Discharge LOS Hours.*?\n(\d+\.\d+)\s+([\d.]+)\n([\d.]+)\n(\d+)%\s+Percentile',
        throughput_text, re.DOTALL
    )
    if m:
        discharge_los_me = _parse_float(m.group(2))
        discharge_los_peers = _parse_float(m.group(3))
        discharge_los_pctile = _parse_float(m.group(4))

    # ---- Admit LOS ----
    admit_los_me = None
    admit_los_peers = None
    admit_los_pctile = None

    m = re.search(
        r'Average Admit LOS Hours.*?\n([\d.]+)\s+([\d.]+)\n([\d.]+)\n(\d+)%\s+Percentile',
        throughput_text, re.DOTALL
    )
    if m:
        admit_los_me = _parse_float(m.group(2))
        admit_los_peers = _parse_float(m.group(3))
        admit_los_pctile = _parse_float(m.group(4))

    # ---- Admission Rate ----
    admission_rate_me = None
    admission_rate_peers = None
    admission_rate_pctile = None

    m = re.search(
        r'Admission Rate % \(When First Attending\)\n([\d.]+%)\n([\d.]+%) ([\d.]+%)\n\([\d,]+/[\d,]+\)\n\([\d,]+/[\d,]+\)\n.*?\n(\d+)%\s+Percentile',
        throughput_text, re.DOTALL
    )
    if not m:
        # Alternative layout: value appears twice on same line
        m = re.search(
            r'Admission Rate.*?\n([\d.]+%)\n([\d.]+%)\s+([\d.]+%)\n\([\d,]+/[\d,]+\)\n\([\d,]+/[\d,]+\)\n([\d.]+)%\s+Percentile',
            throughput_text, re.DOTALL
        )
    if not m:
        # Simpler fallback
        m = re.search(
            r'Admission Rate.*?\n([\d.]+%)\s*\n([\d.]+%)\s+([\d.]+%)\n.*?\([\d,]+/[\d,]+\).*?\n(\d+)%\s+Percentile',
            throughput_text, re.DOTALL
        )
    if m:
        admission_rate_me = _parse_float(m.group(1))
        admission_rate_peers = _parse_float(m.group(3))
        admission_rate_pctile = _parse_float(m.group(4))

    # ---- Bed Request (Median Minutes to Bed Request) ----
    bed_request_me = None
    bed_request_peers = None
    bed_request_pctile = None

    # Bed request layout variants:
    # Variant A: "140.5\n140.5\n159\n36% Percentile"  (decimal, me on two lines)
    # Variant B: "177 177\n174\n49% Percentile"         (two ints on same line)
    # Variant C: "143\n143\n171\n28% Percentile"        (int, me on two lines)
    m = re.search(
        r'Bed Request \(When First Attending\)\n'
        r'([\d.]+)\s+([\d.]+)\n([\d.]+)\n(\d+)%\s+Percentile',
        throughput_text, re.IGNORECASE
    )
    if not m:
        # variant where me is on two separate lines
        m = re.search(
            r'Bed Request \(When First Attending\)\n'
            r'([\d.]+)\n([\d.]+)\n([\d.]+)\n(\d+)%\s+Percentile',
            throughput_text, re.IGNORECASE
        )
        if m:
            bed_request_me = _parse_float(m.group(2))
            bed_request_peers = _parse_float(m.group(3))
            bed_request_pctile = _parse_float(m.group(4))
    else:
        bed_request_me = _parse_float(m.group(2))
        bed_request_peers = _parse_float(m.group(3))
        bed_request_pctile = _parse_float(m.group(4))
    # If still None, try the "Median Mintues" label variant
    if bed_request_me is None:
        m = re.search(
            r'Median M[ia]ntues? to Bed Request.*?\n([\d.]+)\n([\d.]+)\n([\d.]+)\n(\d+)%\s+Percentile',
            throughput_text, re.DOTALL | re.IGNORECASE
        )
        if not m:
            m = re.search(
                r'Median M[ia]ntues? to Bed Request.*?\n([\d.]+)\s+([\d.]+)\n([\d.]+)\n(\d+)%\s+Percentile',
                throughput_text, re.DOTALL | re.IGNORECASE
            )
        if m:
            bed_request_me = _parse_float(m.group(2))
            bed_request_peers = _parse_float(m.group(3))
            bed_request_pctile = _parse_float(m.group(4))

    # ---- 72 Hour Returns ----
    returns72_me = None
    returns72_peers = None
    returns72_pctile = None

    m = re.search(
        r'72 Hour Returns \(When First Attending\)\n([\d.]+%)\s+([\d.]+%)\n([\d.]+%)\n(\d+)%\s+Percentile',
        throughput_text, re.DOTALL
    )
    if m:
        returns72_me = _parse_float(m.group(1))
        returns72_peers = _parse_float(m.group(3))
        returns72_pctile = _parse_float(m.group(4))

    # ---- 72 Hour Readmits ----
    readmits72_me = None
    readmits72_peers = None
    readmits72_pctile = None

    m = re.search(
        r'72 Hour Readmits \(When First Attending\)\n([\d.]+%)\s+([\d.]+%)\n([\d.]+%)\n(\d+)%\s+Percentile',
        throughput_text, re.DOTALL
    )
    if m:
        readmits72_me = _parse_float(m.group(1))
        readmits72_peers = _parse_float(m.group(3))
        readmits72_pctile = _parse_float(m.group(4))

    # ---- Radiology Orders ----
    rad_orders_me = None
    rad_orders_peers = None
    rad_orders_pctile = None

    m = re.search(
        r'% Encounters with Radiology Orders.*?\n([\d.]+%)\n([\d.]+%)\n([\d.]+%)\n([\d.]+%)\n.*?Percentile',
        throughput_text, re.DOTALL
    )
    if not m:
        m = re.search(
            r'% Encounters with Radiology Orders.*?\n([\d.]+%)\n([\d.]+%)\n([\d.]+%)\n([\d.]+%)',
            throughput_text, re.DOTALL
        )
    if m:
        # Layout: me%, me%, peers%, pctile%
        rad_orders_me = _parse_float(m.group(2))
        rad_orders_peers = _parse_float(m.group(3))
        rad_orders_pctile = _parse_float(m.group(4))

    # ---- Lab Orders ----
    lab_orders_me = None
    lab_orders_peers = None
    lab_orders_pctile = None

    m = re.search(
        r'% Encounters with Lab Orders.*?\n([\d.]+%)\s+([\d.]+%)\n([\d.]+%)\n(\d+)%\s+Percentile',
        throughput_text, re.DOTALL
    )
    if m:
        lab_orders_me = _parse_float(m.group(1))
        lab_orders_peers = _parse_float(m.group(3))
        lab_orders_pctile = _parse_float(m.group(4))

    # ----------------------------------------------------------------
    # Page 4: Qgenda shifts — count shifts in the reporting period
    # ----------------------------------------------------------------
    shift_page_text = pages[3] if len(pages) > 3 else ''
    shift_count = len(re.findall(r'- \d+Hrs', shift_page_text))

    # ----------------------------------------------------------------
    # Page 5: Patients per hour (New Patient Assignments Per Hour)
    # ----------------------------------------------------------------
    pts_page_text = pages[4] if len(pages) > 4 else ''

    pts_per_hour_me = None
    pts_per_hour_peers = None
    pts_per_hour_pctile = None

    m = re.search(
        r'Average New Patient Assignments Per Hour Evaluated Evaluated\n([\d.]+)\n([\d.]+)\n([\d.]+)\n.*?(\d+)%\s+Percentile',
        pts_page_text, re.DOTALL
    )
    if m:
        pts_per_hour_me = _parse_float(m.group(1))
        pts_per_hour_peers = _parse_float(m.group(3))
        pts_per_hour_pctile = _parse_float(m.group(4))

    # ---- Patients per hour by shift type ----
    shift_data = _parse_shift_data(pts_page_text)

    # ----------------------------------------------------------------
    # Page 6: Billing codes for the provider row
    # ----------------------------------------------------------------
    billing_text = pages[5] if len(pages) > 5 else ''

    billing_level3 = None
    billing_level4 = None
    billing_level5 = None

    # The provider row starts with "LASTNAME, FIRSTNAME [MIDDLENAME-]SUFFIX[..]"
    # (name may be truncated with dots) followed by billing % columns:
    # level2% level3% level4% level5% visits
    # Match any provider name in "LAST, FIRST..." format.
    m = re.search(
        r'[A-Z]+,\s+[A-Z][A-Z\s.-]+\s+([\d.]+%)\s+([\d.]+%)\s+([\d.]+%)\s+([\d.]+%)\s+\d+',
        billing_text
    )
    if m:
        # Values are percentages (e.g. "15.6%"); store as rounded integer
        def _pct_to_int(s):
            v = _parse_float(s)
            return int(round(v)) if v is not None else None
        billing_level3 = _pct_to_int(m.group(2))
        billing_level4 = _pct_to_int(m.group(3))
        billing_level5 = _pct_to_int(m.group(4))

    # ----------------------------------------------------------------
    # Page 7 (summary): Discharge rate, ICU rate, and rad/lab admit/disc
    # ----------------------------------------------------------------
    discharge_rate_me = None
    discharge_rate_peers = None
    discharge_rate_pctile = None
    icu_rate_me = None
    icu_rate_peers = None
    icu_rate_pctile = None
    rad_admit_me = None
    rad_admit_peers = None
    rad_disc_me = None
    rad_disc_peers = None

    if summary_text:
        # Discharge Rate — values may be on same line or separate lines
        m = re.search(
            r'Discharge Rate\n([\d.]+%)\s+([\d.]+%)\n.*?([\d.]+%)\s+Percentile',
            summary_text, re.DOTALL
        )
        if not m:
            m = re.search(
                r'Discharge Rate\n([\d.]+%)\n([\d.]+%)\n.*?([\d.]+%)\s+Percentile',
                summary_text, re.DOTALL
            )
        if m:
            discharge_rate_me = _parse_float(m.group(1))
            discharge_rate_peers = _parse_float(m.group(2))
            discharge_rate_pctile = _parse_float(m.group(3))

        # ICU Rate — same-line or separate-line variants
        m = re.search(
            r'Admission to ICU Rate\n([\d.]+%)\s+([\d.]+%)\n.*?(\d+)%\s+Percentile',
            summary_text, re.DOTALL
        )
        if not m:
            m = re.search(
                r'Admission to ICU Rate\n([\d.]+%)\n([\d.]+%)\n.*?(\d+)%\s+Percentile',
                summary_text, re.DOTALL
            )
        if m:
            icu_rate_me = _parse_float(m.group(1))
            icu_rate_peers = _parse_float(m.group(2))
            icu_rate_pctile = _parse_float(m.group(3))

        # Radiology: Admit and Discharge %
        m = re.search(
            r'% with Radiology Orders\n[\d.]+%\s+[\d.]+%\n[\d.]+%\s+Percentile\n([\d.]+%)\nAdmit\n([\d.]+%)',
            summary_text, re.DOTALL
        )
        if not m:
            m = re.search(
                r'% with Radiology Orders\n[\d.]+%\s+[\d.]+%\n[\d.]+%\s+Percentile\n([\d.]+%)\nAdmit\s+([\d.]+%)',
                summary_text, re.DOTALL
            )
        if m:
            rad_admit_me = _parse_float(m.group(1))
            rad_admit_peers = _parse_float(m.group(2))

        # Radiology discharge — first "Discharge" occurrence in summary
        m = re.search(r'([\d.]+%)\nDischarge\s+([\d.]+%)', summary_text, re.DOTALL)
        if not m:
            m = re.search(r'Discharge\s+([\d.]+%)\s+([\d.]+%)', summary_text, re.DOTALL)
        if m:
            rad_disc_me = _parse_float(m.group(1))
            rad_disc_peers = _parse_float(m.group(2))

        # Lab: Admit and Discharge % — same layout as radiology
        lab_admit_me = None
        lab_admit_peers = None
        lab_disc_me = None
        lab_disc_peers = None

        m = re.search(
            r'% with Lab Orders\n[\d.]+%\s+[\d.]+%\n[\d.]+%\s*(?:Percentile)?\n([\d.]+%)\nAdmit\n([\d.]+%)',
            summary_text, re.DOTALL
        )
        if not m:
            m = re.search(
                r'% with Lab Orders\n[\d.]+%\s+[\d.]+%\n[\d.]+%\s*(?:Percentile)?\n([\d.]+%)\nAdmit\s+([\d.]+%)',
                summary_text, re.DOTALL
            )
        if m:
            lab_admit_me = _parse_float(m.group(1))
            lab_admit_peers = _parse_float(m.group(2))

        # Lab discharge — find the section between "Lab Orders" and "72 Hour"
        lab_section_m = re.search(r'% with Lab Orders.*?72 Hour', summary_text, re.DOTALL)
        if lab_section_m:
            lab_sec = lab_section_m.group(0)
            dm = re.search(r'([\d.]+%)\nDischarge\s+([\d.]+%)', lab_sec)
            if not dm:
                dm = re.search(r'Discharge\s+([\d.]+%)\s+([\d.]+%)', lab_sec)
            if dm:
                lab_disc_me = _parse_float(dm.group(1))
                lab_disc_peers = _parse_float(dm.group(2))

    # ----------------------------------------------------------------
    # ESI distribution — from page 3 or 7
    # ----------------------------------------------------------------
    esi1 = None
    esi2 = None
    esi3 = None
    esi4 = None
    esi5 = None

    # Two possible formats:
    # 5-level: "0.80% 20.00% 49.60% 23.20% 6.40%\n1-Critical 2-Emergency 3-Urgent 4-Non-Urgent 5-Minor"
    # 4-level: "21.57% 58.82% 16.18% 3.43%\n2-Emergency 3-Urgent 4-Non-Urgent 5-Minor"
    m5 = re.search(
        r'([\d.]+%)\s+([\d.]+%)\s+([\d.]+%)\s+([\d.]+%)\s+([\d.]+%)\s*\n'
        r'1-Critical\s+2-Emergency\s+3-Urgent\s+4-Non-Urgent\s+5-Minor',
        throughput_text
    )
    if not m5:
        m5 = re.search(
            r'([\d.]+%)\s+([\d.]+%)\s+([\d.]+%)\s+([\d.]+%)\s+([\d.]+%)\s*\n'
            r'1-Critical\s+2-Emergency\s+3-Urgent\s+4-Non-Urgent\s+5-Minor',
            summary_text
        )
    if m5:
        esi1 = _parse_float(m5.group(1))
        esi2 = _parse_float(m5.group(2))
        esi3 = _parse_float(m5.group(3))
        esi4 = _parse_float(m5.group(4))
        esi5 = _parse_float(m5.group(5))
    else:
        # 4-level (no ESI 1)
        m4 = re.search(
            r'([\d.]+%)\s+([\d.]+%)\s+([\d.]+%)\s+([\d.]+%)\s*\n'
            r'2-Emergency\s+3-Urgent\s+4-Non-Urgent\s+5-Minor',
            throughput_text
        )
        if not m4:
            m4 = re.search(
                r'([\d.]+%)\s+([\d.]+%)\s+([\d.]+%)\s+([\d.]+%)\s*\n'
                r'2-Emergency\s+3-Urgent\s+4-Non-Urgent\s+5-Minor',
                summary_text
            )
        if m4:
            esi1 = None
            esi2 = _parse_float(m4.group(1))
            esi3 = _parse_float(m4.group(2))
            esi4 = _parse_float(m4.group(3))
            esi5 = _parse_float(m4.group(4))

    # ----------------------------------------------------------------
    # Assemble result
    # ----------------------------------------------------------------
    return {
        'month': month,
        'year': year,
        'patients': patients,
        # Discharge LOS
        'discharge_los_me': discharge_los_me,
        'discharge_los_peers': discharge_los_peers,
        'discharge_los_pctile': discharge_los_pctile,
        # Admit LOS
        'admit_los_me': admit_los_me,
        'admit_los_peers': admit_los_peers,
        'admit_los_pctile': admit_los_pctile,
        # Admission rate
        'admission_rate_me': admission_rate_me,
        'admission_rate_peers': admission_rate_peers,
        'admission_rate_pctile': admission_rate_pctile,
        # Bed request
        'bed_request_me': bed_request_me,
        'bed_request_peers': bed_request_peers,
        'bed_request_pctile': bed_request_pctile,
        # 72h returns
        'returns72_me': returns72_me,
        'returns72_peers': returns72_peers,
        'returns72_pctile': returns72_pctile,
        # 72h readmits
        'readmits72_me': readmits72_me,
        'readmits72_peers': readmits72_peers,
        'readmits72_pctile': readmits72_pctile,
        # Radiology orders
        'rad_orders_me': rad_orders_me,
        'rad_orders_peers': rad_orders_peers,
        'rad_orders_pctile': rad_orders_pctile,
        # Lab orders
        'lab_orders_me': lab_orders_me,
        'lab_orders_peers': lab_orders_peers,
        'lab_orders_pctile': lab_orders_pctile,
        # Pts per hour
        'pts_per_hour_me': pts_per_hour_me,
        'pts_per_hour_peers': pts_per_hour_peers,
        'pts_per_hour_pctile': pts_per_hour_pctile,
        # Discharge rate
        'discharge_rate_me': discharge_rate_me,
        'discharge_rate_peers': discharge_rate_peers,
        'discharge_rate_pctile': discharge_rate_pctile,
        # ICU rate
        'icu_rate_me': icu_rate_me,
        'icu_rate_peers': icu_rate_peers,
        'icu_rate_pctile': icu_rate_pctile,
        # Radiology admit/discharge split
        'rad_admit_me': rad_admit_me,
        'rad_admit_peers': rad_admit_peers,
        'rad_disc_me': rad_disc_me,
        'rad_disc_peers': rad_disc_peers,
        # Lab admit/discharge split
        'lab_admit_me': lab_admit_me,
        'lab_admit_peers': lab_admit_peers,
        'lab_disc_me': lab_disc_me,
        'lab_disc_peers': lab_disc_peers,
        # ESI
        'esi1': esi1,
        'esi2': esi2,
        'esi3': esi3,
        'esi4': esi4,
        'esi5': esi5,
        # Billing
        'billing_level3': billing_level3,
        'billing_level4': billing_level4,
        'billing_level5': billing_level5,
        # Shift count (from Qgenda page)
        'shift_count': shift_count,
        # Shift breakdown
        'shift_data': shift_data,
    }
