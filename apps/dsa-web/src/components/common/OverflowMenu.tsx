import type React from 'react';
import { useEffect, useId, useRef, useState } from 'react';
import { MoreHorizontal } from 'lucide-react';

interface OverflowMenuProps {
  /** Accessible label / tooltip for the trigger button. */
  label: string;
  /** Menu content (items). Receives a `close` callback to dismiss after a tap. */
  children: (close: () => void) => React.ReactNode;
  className?: string;
  /** Popover horizontal alignment relative to the trigger. */
  align?: 'left' | 'right';
}

/**
 * Compact "更多" overflow trigger + popover. Used to collapse secondary actions
 * on small screens. Closes on outside click and Escape. Content is provided by
 * the caller so it can host toggles, radio options or plain actions.
 */
export const OverflowMenu: React.FC<OverflowMenuProps> = ({
  label,
  children,
  className = '',
  align = 'right',
}) => {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const menuId = useId();
  const close = () => setOpen(false);

  useEffect(() => {
    if (!open) {
      return undefined;
    }
    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target;
      if (target instanceof Node && containerRef.current?.contains(target)) {
        return;
      }
      setOpen(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [open]);

  return (
    <div ref={containerRef} className={`relative ${className}`}>
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-label={label}
        onClick={() => setOpen((prev) => !prev)}
        className="home-surface-button flex h-10 w-10 items-center justify-center rounded-xl text-secondary-text hover:text-foreground"
      >
        <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
      </button>
      {open ? (
        <div
          id={menuId}
          role="menu"
          className={`absolute top-11 z-[120] min-w-[12rem] max-w-[min(18rem,calc(100vw-1.5rem))] overflow-hidden rounded-xl border border-subtle bg-elevated p-1.5 text-sm text-foreground shadow-2xl ${
            align === 'right' ? 'right-0' : 'left-0'
          }`}
        >
          {children(close)}
        </div>
      ) : null}
    </div>
  );
};

export default OverflowMenu;
