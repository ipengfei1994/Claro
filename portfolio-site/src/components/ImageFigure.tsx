import { Maximize2 } from "lucide-react";
import { useState } from "react";
import { Modal } from "@/components/Modal";

interface ImageFigureProps {
  src: string;
  alt: string;
  title: string;
  caption: string;
  source?: string;
  className?: string;
}

export function ImageFigure({ src, alt, title, caption, source, className = "" }: ImageFigureProps) {
  const [open, setOpen] = useState(false);

  return (
    <figure className={className}>
      <div className="frame">
        <div className="frame__bar">
          <span>{title}</span>
          <button
            type="button"
            className="inline-flex items-center gap-2 border-0 bg-transparent p-0 text-muted"
            onClick={() => setOpen(true)}
          >
            <Maximize2 size={13} aria-hidden="true" />
            查看原图
          </button>
        </div>
        <button
          type="button"
          className="block w-full border-0 bg-transparent p-0"
          onClick={() => setOpen(true)}
          aria-label={`放大查看：${title}`}
        >
          <img className="screenshot" src={src} alt={alt} loading="lazy" />
        </button>
      </div>
      <figcaption className="figure-caption">
        <span>{caption}</span>
        {source && <span className="font-mono text-[10px]">{source}</span>}
      </figcaption>
      <Modal open={open} onClose={() => setOpen(false)} title={title}>
        <img src={src} alt={alt} className="mx-auto h-auto max-w-full" />
        <p className="mt-5 max-w-reading text-sm leading-6 text-muted">{caption}</p>
        {source && <p className="mt-2 font-mono text-[10px] text-muted">{source}</p>}
      </Modal>
    </figure>
  );
}
