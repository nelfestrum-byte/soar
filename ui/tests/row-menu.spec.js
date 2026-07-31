import { afterEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import RowMenu from '../src/components/RowMenu.vue'

let wrapper = null

function mountMenu() {
  wrapper = mount(RowMenu, {
    attachTo: document.body,
    slots: { default: '<button class="delete-item">Delete</button>' },
  })
  return wrapper
}

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
})

describe('RowMenu', () => {
  it('renders closed by default', () => {
    mountMenu()
    expect(wrapper.find('.row-menu-panel').exists()).toBe(false)
  })

  it('renders the more_vert icon in the toggle, not a literal glyph', () => {
    mountMenu()
    const toggle = wrapper.find('.row-menu-toggle')
    expect(toggle.find('.material-symbols-outlined').exists()).toBe(true)
    expect(toggle.text()).toContain('more_vert')
  })

  it('opens on toggle click and shows slot content', async () => {
    mountMenu()
    await wrapper.find('.row-menu-toggle').trigger('click')
    expect(wrapper.find('.row-menu-panel').exists()).toBe(true)
    expect(wrapper.find('.delete-item').exists()).toBe(true)
  })

  it('closes after clicking an item inside the slot', async () => {
    mountMenu()
    await wrapper.find('.row-menu-toggle').trigger('click')
    await wrapper.find('.delete-item').trigger('click')
    expect(wrapper.find('.row-menu-panel').exists()).toBe(false)
  })

  it('closes on outside click', async () => {
    mountMenu()
    await wrapper.find('.row-menu-toggle').trigger('click')
    expect(wrapper.find('.row-menu-panel').exists()).toBe(true)
    document.body.click()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.row-menu-panel').exists()).toBe(false)
  })
})
