import { clsx, type ClassValue } from "clsx"
import { extendTailwindMerge } from "tailwind-merge"
import { typeRoles } from "@/lib/type-roles"
// 글자 역할(text-<역할>)은 글자 크기 묶음이다. 알려 주지 않으면 tailwind-merge가 글자 색으로 보고 뒤의 text-<색>과 겹친다며 지운다.
const twMerge = extendTailwindMerge({ extend: { theme: { text: [...typeRoles] } } })
export function cn(...inputs: ClassValue[]) { return twMerge(clsx(inputs)) }
