import { useRef, type ReactNode } from 'react';
import { Trans } from '@lingui/react/macro';
import { X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { useIsMobile } from '@/hooks/use-mobile';

export type MetricSheetSize = 'standard' | 'wide';

interface MetricDetailSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  size: MetricSheetSize;
  title: ReactNode;
  description: ReactNode;
  children: ReactNode;
}

/** Shared responsive shell for Training peer-metric drill-downs. */
export default function MetricDetailSheet({
  open,
  onOpenChange,
  size,
  title,
  description,
  children,
}: MetricDetailSheetProps) {
  const isMobile = useIsMobile();
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side={isMobile ? 'bottom' : 'right'}
        initialFocus={closeButtonRef}
        showCloseButton={false}
        data-metric-size={size}
        className={`gap-0 overflow-hidden p-0 ${
          isMobile
            ? 'max-h-[92dvh] w-full rounded-t-xl'
            : size === 'wide'
              ? 'w-full sm:!max-w-[52rem]'
              : 'w-full sm:!max-w-[34rem]'
        }`}
      >
        <SheetClose
          render={(
            <Button
              ref={closeButtonRef}
              variant="ghost"
              size="icon-sm"
              className="absolute right-3 top-3 z-10"
            />
          )}
        >
          <X aria-hidden="true" />
          <span className="sr-only"><Trans>Close</Trans></span>
        </SheetClose>

        <SheetHeader className="shrink-0 px-5 pb-4 pt-5 pr-14 sm:px-7 sm:pb-5 sm:pt-7">
          <SheetTitle className="text-xl font-semibold tracking-[-0.02em]">
            {title}
          </SheetTitle>
          <SheetDescription className="max-w-[70ch]">
            {description}
          </SheetDescription>
        </SheetHeader>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-7 sm:px-7">
          {children}
        </div>
      </SheetContent>
    </Sheet>
  );
}
