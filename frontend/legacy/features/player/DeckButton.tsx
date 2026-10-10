import { formatBytes } from './ExportPanel';
import { DownloadIcon, SlidesIcon } from './icons';
import { useExportJob } from './useExportJob';

interface DeckButtonProps {
  messageId: string | null;
  disabled?: boolean;
}

/**
 * Building a PowerPoint deck out of the explanation.
 *
 * It owns its own job rather than sharing the fragment panel's: a deck takes
 * no settings, so putting it behind the same dialog would mean opening a
 * panel of range controls that do not apply to it. One button, one result.
 */
export const DeckButton: React.FC<DeckButtonProps> = ({ messageId, disabled = false }) => {
  const { job, error, isBusy, start } = useExportJob();

  if (job?.status === 'done' && job.download_url) {
    return (
      <a
        href={job.download_url}
        download
        data-testid="deck-download"
        className="px-3 py-2.5 rounded-xl text-sm font-medium bg-green-600 hover:bg-green-500
                   text-white flex items-center gap-2"
      >
        <DownloadIcon />
        Deck {formatBytes(job.output_bytes)}
      </a>
    );
  }

  return (
    <button
      onClick={() => messageId && start('pptx', messageId, {})}
      disabled={disabled || !messageId || isBusy}
      data-testid="deck-button"
      title={error || 'Build a PowerPoint deck from this explanation'}
      className={`px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-200
                  flex items-center gap-2 ${
                    disabled || !messageId || isBusy
                      ? 'bg-dark-700 text-gray-600 cursor-not-allowed'
                      : error
                      ? 'bg-red-900/60 text-red-200 hover:bg-red-900'
                      : 'bg-dark-600 hover:bg-dark-500 text-white'
                  }`}
    >
      <SlidesIcon />
      {isBusy ? 'Building...' : error ? 'Retry deck' : 'Deck'}
    </button>
  );
};
