// Single point of Monaco loading — no CDN fetch of any kind. `?worker` is Vite's built-in
// worker-import syntax (no plugin needed); it bundles the worker as a
// separate chunk served from the same origin as the rest of the UI, which is
// what keeps this working on an air-gapped stand.
import EditorWorker from 'monaco-editor/editor/editor.worker?worker'

let monacoPromise = null

export function loadMonaco() {
  if (!monacoPromise) {
    monacoPromise = import('monaco-editor/editor/editor.api').then((monaco) => {
      self.MonacoEnvironment = {
        getWorker: () => new EditorWorker(),
      }
      return monaco
    })
  }
  return monacoPromise
}
