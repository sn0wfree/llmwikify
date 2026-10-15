import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../ui/dialog';
import { Button } from '../ui/button';
import { FileText } from 'lucide-react';

interface PageExistsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  pageName: string;
  wordCount: number;
  contentPreview: string;
  onConfirm: () => void;
  onCancel?: () => void;
}

const PREVIEW_LIMIT = 500;

export function PageExistsDialog({
  open,
  onOpenChange,
  pageName,
  wordCount,
  contentPreview,
  onConfirm,
  onCancel,
}: PageExistsDialogProps) {
  const truncated = contentPreview.length > PREVIEW_LIMIT;
  const preview = truncated
    ? contentPreview.slice(0, PREVIEW_LIMIT) + '…'
    : contentPreview;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <div className="flex items-start gap-3">
            <FileText className="w-5 h-5 text-muted-foreground mt-0.5 shrink-0" />
            <div className="flex-1 min-w-0">
              <DialogTitle>Page already exists</DialogTitle>
              <DialogDescription className="mt-1.5">
                <span className="font-mono text-xs">{pageName}</span> already
                exists ({wordCount.toLocaleString()} words). Updating will
                overwrite the current content.
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>
        <div className="space-y-2">
          <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Existing preview
          </div>
          <pre className="max-h-48 overflow-y-auto rounded-md border border-border/40 bg-muted/40 p-3 text-xs font-mono whitespace-pre-wrap break-words">
            {preview || '(empty)'}
          </pre>
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => {
              onCancel?.();
              onOpenChange(false);
            }}
          >
            Cancel
          </Button>
          <Button
            onClick={() => {
              onConfirm();
              onOpenChange(false);
            }}
          >
            Update page
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
