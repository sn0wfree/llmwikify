import { useState } from 'react';
import { api, type ResearchReport } from '../api';

interface Props {
  researchId: string;
  report: ResearchReport;
  onClose: () => void;
}

export function ResearchRating({ researchId, report, onClose }: Props) {
  const [rating, setRating] = useState(0);
  const [hoverRating, setHoverRating] = useState(0);
  const [feedback, setFeedback] = useState('');
  const [sourceRatings, setSourceRatings] = useState<Record<string, number>>({});
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async () => {
    if (rating === 0) return;
    setSubmitting(true);
    try {
      await api.research.rate(researchId, rating, sourceRatings, feedback);
      setSubmitted(true);
    } catch { /* silent */ }
    setSubmitting(false);
  };

  if (submitted) {
    return (
      <div className="p-4 bg-[var(--bg-secondary)] rounded border border-[var(--border)] text-center">
        <div className="text-lg mb-2">Thank you for your feedback!</div>
        <button onClick={onClose} className="text-sm text-[var(--accent)] hover:underline">Close</button>
      </div>
    );
  }

  return (
    <div className="p-4 bg-[var(--bg-secondary)] rounded border border-[var(--border)]">
      <h3 className="text-sm font-bold mb-3">Rate this research</h3>

      {/* Star rating */}
      <div className="flex items-center gap-1 mb-3">
        {[1, 2, 3, 4, 5].map(star => (
          <button
            key={star}
            className={`text-2xl transition-colors ${
              star <= (hoverRating || rating) ? 'text-yellow-400' : 'text-[var(--text-secondary)]'
            }`}
            onClick={() => setRating(star)}
            onMouseEnter={() => setHoverRating(star)}
            onMouseLeave={() => setHoverRating(0)}
          >
            ★
          </button>
        ))}
        {rating > 0 && <span className="text-sm text-[var(--text-secondary)] ml-2">{rating}/5</span>}
      </div>

      {/* Source ratings */}
      {report.sources && report.sources.length > 0 && (
        <div className="mb-3">
          <div className="text-xs text-[var(--text-secondary)] mb-1">Rate sources (optional):</div>
          <div className="space-y-1 max-h-32 overflow-y-auto">
            {report.sources.map(src => (
              <div key={src.id} className="flex items-center gap-2 text-xs">
                <span className="flex-1 truncate">{src.title}</span>
                <span className="text-[var(--text-secondary)]">[{src.source_type}]</span>
                <div className="flex gap-0.5">
                  {[1, 2, 3, 4, 5].map(s => (
                    <button
                      key={s}
                      className={`text-sm ${
                        s <= (sourceRatings[src.id] || 0) ? 'text-yellow-400' : 'text-[var(--text-secondary)]'
                      }`}
                      onClick={() => setSourceRatings(prev => ({ ...prev, [src.id]: s }))}
                    >
                      ★
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Feedback */}
      <div className="mb-3">
        <textarea
          value={feedback}
          onChange={e => setFeedback(e.target.value)}
          placeholder="Feedback (optional)..."
          className="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded text-sm resize-none"
          rows={2}
        />
      </div>

      {/* Actions */}
      <div className="flex gap-2 justify-end">
        <button onClick={onClose} className="px-3 py-1.5 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
          Skip
        </button>
        <button
          onClick={handleSubmit}
          disabled={rating === 0 || submitting}
          className="px-4 py-1.5 bg-[var(--accent)] text-white rounded text-sm disabled:opacity-50"
        >
          {submitting ? 'Submitting...' : 'Submit'}
        </button>
      </div>
    </div>
  );
}
