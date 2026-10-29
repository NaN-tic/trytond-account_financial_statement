from pathlib import Path

from fpdf import FPDF


class FinancialStatementPDF(FPDF):
    """Render financial statement rows directly, with repeating page headers."""

    def __init__(self, margin):
        super().__init__(format='A4')
        self.set_margins(margin, margin, margin)
        self.set_auto_page_break(False, margin=max(10, margin))
        fonts = Path(__file__).with_name('fonts')
        self.add_font('DejaVu', fname=fonts / 'DejaVuSans.ttf')
        self.add_font('DejaVu', style='B', fname=fonts / 'DejaVuSans-Bold.ttf')
        self.alias_nb_pages()

    def header(self):
        self.set_text_color(0)
        self.set_font('DejaVu', 'B', 11)
        self.multi_cell(0, 5, self.heading, new_x='LMARGIN', new_y='NEXT')
        self.set_font('DejaVu', size=8)
        self.multi_cell(0, 4, self.tax_identifier, new_x='LMARGIN', new_y='NEXT')
        self.ln(2)
        count = len(self.columns) - 1
        self.table_font_size = 7 if count > 8 else 8
        label_width = self.epw * (0.30 if count > 5 else 0.40)
        self.widths = ([label_width] + [(self.epw - label_width) / count] * count
            if count else [self.epw])
        self.aligns = ['L'] + ['R'] * count
        self.row(self.columns, bold=True, fill=True, paginate=False)
        self.body_top = self.y

    def footer(self):
        self.set_y(-8)
        self.set_text_color(0)
        self.set_font('DejaVu', size=7)
        self.cell(0, 4, f'{self.page_no()} / {{nb}}', align='R')

    def row(self, values, bold=False, fill=False, paginate=True, detail=False):
        self.set_font('DejaVu', 'B' if bold else '', self.table_font_size)
        self.set_text_color(120 if detail else 0)
        lines = []
        for width, value in zip(self.widths, values):
            text = '' if value is None else str(value)
            if '\n' not in text and self.get_string_width(text) <= width - 2:
                lines.append([text])
            else:
                lines.append(self.multi_cell(width, 4, text,
                    dry_run=True, output='LINES'))
        count = max(map(len, lines), default=1)
        if (paginate and self.y + count * 4 > self.h - self.b_margin
                and count * 4 <= self.h - self.b_margin - self.body_top):
            self.add_page(orientation=self.cur_orientation)
            self.set_font('DejaVu', 'B' if bold else '', self.table_font_size)
            self.set_text_color(120 if detail else 0)
        for index in range(count):
            if paginate and self.y + 4 > self.h - self.b_margin:
                self.add_page(orientation=self.cur_orientation)
                self.set_font('DejaVu', 'B' if bold else '', self.table_font_size)
                self.set_text_color(120 if detail else 0)
            self.set_x(self.l_margin)
            self.set_fill_color(235, 235, 235)
            for width, cell_lines, align in zip(self.widths, lines, self.aligns):
                text = cell_lines[index] if index < len(cell_lines) else ''
                self.cell(width, 4, text, align=align, fill=fill)
            self.ln(4)
