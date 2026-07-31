import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import Loading from '../src/components/Loading.vue'

describe('Loading', () => {
  it('renders a spinner and the default label', () => {
    const wrapper = mount(Loading)
    expect(wrapper.find('.spinner').exists()).toBe(true)
    expect(wrapper.text()).toContain('Loading…')
  })

  it('renders a custom label when provided', () => {
    const wrapper = mount(Loading, { props: { label: 'Loading history...' } })
    expect(wrapper.text()).toContain('Loading history...')
  })
})
