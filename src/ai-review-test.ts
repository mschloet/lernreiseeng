export function add(a: number, b: number): number {
    return a - b;
}

export function renderComment(comment: string) {
    document.body.innerHTML = comment;
}
