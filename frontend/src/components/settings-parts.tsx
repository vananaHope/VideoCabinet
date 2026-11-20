import { cn } from "@/lib/utils"
import type { ComponentProps, HTMLAttributes, ReactNode } from "react"

type SectionProps = Omit<ComponentProps<"section">, "title" | "children"> & {
  title: string; description?: ReactNode; headingId?: string; children: ReactNode
}

/** 설정의 한 분류(일반·추천·번역·받아쓰기·백업·업데이트). 구역 제목과 설명 아래에 설정 카드가 같은 간격으로 쌓인다. */
export function SettingsSection({ title, description, headingId, children, className, ...props }: SectionProps) {
  return <section aria-labelledby={props["aria-label"] ? undefined : headingId} {...props} className={cn("space-y-3", className)}>
    <div className="space-y-1">
      <h2 id={headingId} className="text-section-title">{title}</h2>
      {description && <p className="text-body text-muted-foreground">{description}</p>}
    </div>
    {children}
  </section>
}

type TitleProps = HTMLAttributes<HTMLHeadingElement> & { [data: `data-${string}`]: string | boolean | undefined }
type CardProps = {
  /** 카드 제목. labelFor가 있으면 그 입력의 라벨로 그린다. */
  title: ReactNode; titleId?: string; titleProps?: TitleProps; labelFor?: string
  /** 제목 옆에 붙는 배지·되돌리기 단추. 생겨도 제목 줄 높이는 그대로다. */
  badge?: ReactNode
  /** 제목 앞 그림(앱 아이콘). */
  icon?: ReactNode
  description?: ReactNode; descriptionId?: string; status?: boolean
  /** 제목 줄 오른쪽 조작 자리(스위치·입력과 저장·단추). 좁으면 설명 아래로 내려간다. */
  control?: ReactNode
  /** 조작 아래의 보조 설명(기본값·주의). */
  note?: ReactNode; noteId?: string; noteStatus?: boolean
  children?: ReactNode
}

/**
 * 설정 카드 하나. 모든 설정 구역이 이 부품으로 여백(안쪽 1rem)·제목(본문 강조)·설명(보조 글자)·조작 자리(제목 줄 오른쪽)를 맞춘다.
 * 첫 자식은 늘 제목 줄이고 조작은 그 안에 있다. 값은 설명이나 children에 본문 크기로 두고 제목보다 크게 쓰지 않는다.
 */
export function SettingsCard({ title, titleId, titleProps, labelFor, badge, icon, description, descriptionId, status, control, note, noteId, noteStatus, children, as = "section", ...props }: CardProps & (
  ({ as?: "section" } & Omit<ComponentProps<"section">, "title" | "children">) | ({ as: "form" } & Omit<ComponentProps<"form">, "title" | "children">)
)) {
  const heading = labelFor ? <label id={titleId} htmlFor={labelFor} className="text-body-strong">{title}</label>
    : <h3 id={titleId} {...titleProps} className="text-body-strong">{title}</h3>
  const body = <>
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
      <div className="flex min-w-0 flex-1 items-center gap-3">
        {icon}
        <div className="min-w-0 flex-1">
          {/* 배지·되돌리기 단추가 나타나도 줄 높이가 바뀌지 않게 제목 줄을 작은 단추 높이에 맞춘다. */}
          <div className="flex min-h-6 flex-wrap items-center gap-2">{heading}{badge}</div>
          {description && <p id={descriptionId} role={status ? "status" : undefined} className="text-body text-muted-foreground">{description}</p>}
        </div>
      </div>
      {control && <div className="flex shrink-0 flex-wrap items-center gap-2">{control}</div>}
    </div>
    {note && <p id={noteId} role={noteStatus ? "status" : undefined} className="text-label text-muted-foreground">{note}</p>}
    {children}
  </>
  const card = "space-y-2 rounded-xl border bg-card p-4"
  if (as === "form") return <form {...(props as ComponentProps<"form">)} className={card}>{body}</form>
  return <section {...(props as ComponentProps<"section">)} className={card}>{body}</section>
}
