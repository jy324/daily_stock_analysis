import type React from 'react';
import { Download, Printer } from 'lucide-react';
import type { AnalysisReport, ReportLanguage, RunDiagnosticStatus } from '../../types/analysis';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';
import { downloadTextFile, formatReportAsMarkdown, reportExportFilename } from '../../utils/reportExport';
import { Button } from '../common';

interface ReportExportActionsProps {
  report: AnalysisReport;
  diagnosticStatus?: RunDiagnosticStatus;
  language?: ReportLanguage;
  className?: string;
}

/**
 * Export controls for a stock analysis report: download as Markdown and
 * print / save-as-PDF (via the browser, scoped by `print-report-root`).
 */
export const ReportExportActions: React.FC<ReportExportActionsProps> = ({
  report,
  diagnosticStatus,
  language = 'zh',
  className = '',
}) => {
  const reportLanguage = normalizeReportLanguage(language);
  const text = getReportText(reportLanguage);

  const handleDownload = () => {
    const markdown = formatReportAsMarkdown(report, reportLanguage, { diagnosticStatus });
    downloadTextFile(reportExportFilename(report), markdown);
  };

  return (
    <div
      data-testid="report-export-actions"
      className={`no-print flex flex-wrap items-center justify-end gap-2 ${className}`}
    >
      <Button variant="ghost" size="sm" onClick={handleDownload}>
        <Download className="h-4 w-4" aria-hidden="true" />
        {text.downloadMarkdown}
      </Button>
      <Button variant="ghost" size="sm" onClick={() => window.print()}>
        <Printer className="h-4 w-4" aria-hidden="true" />
        {text.print}
      </Button>
    </div>
  );
};
