import { describe, expect, it } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import * as monaco from 'monaco-editor/editor/editor.api'
import CodeEditor from '../src/components/CodeEditor.vue'

function lastStub() {
  const results = monaco.editor.create.mock.results
  return results[results.length - 1].value
}

describe('CodeEditor', () => {
  it('creates the editor with the given value, language and readOnly', async () => {
    mount(CodeEditor, { props: { modelValue: 'print(1)', language: 'python', readOnly: true } })
    await flushPromises()

    const [, options] = monaco.editor.create.mock.calls.at(-1)
    expect(options.value).toBe('print(1)')
    expect(options.language).toBe('python')
    expect(options.readOnly).toBe(true)
  })

  it('emits update:modelValue when the editor content changes', async () => {
    const wrapper = mount(CodeEditor, { props: { modelValue: 'a' } })
    await flushPromises()

    const stub = lastStub()
    const onChange = stub.onDidChangeModelContent.mock.calls[0][0]
    stub.setValue('b')
    onChange()

    expect(wrapper.emitted('update:modelValue')[0]).toEqual(['b'])
  })

  it('calls setValue when modelValue prop changes externally', async () => {
    const wrapper = mount(CodeEditor, { props: { modelValue: 'a' } })
    await flushPromises()
    const stub = lastStub()

    await wrapper.setProps({ modelValue: 'new' })

    expect(stub.setValue).toHaveBeenCalledWith('new')
  })

  it('does not call setValue when modelValue prop equals the editor value', async () => {
    const wrapper = mount(CodeEditor, { props: { modelValue: 'a' } })
    await flushPromises()
    const stub = lastStub()

    await wrapper.setProps({ modelValue: 'a' })

    expect(stub.setValue).not.toHaveBeenCalled()
  })

  it('calls updateOptions({readOnly}) when readOnly prop changes', async () => {
    const wrapper = mount(CodeEditor, { props: { modelValue: 'a', readOnly: false } })
    await flushPromises()
    const stub = lastStub()

    await wrapper.setProps({ readOnly: true })

    expect(stub.updateOptions).toHaveBeenCalledWith({ readOnly: true })
  })

  it('disposes the editor on unmount', async () => {
    const wrapper = mount(CodeEditor, { props: { modelValue: 'a' } })
    await flushPromises()
    const stub = lastStub()

    wrapper.unmount()

    expect(stub.dispose).toHaveBeenCalled()
  })
})
