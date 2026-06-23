import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { OverflowMenu } from '../OverflowMenu';

describe('OverflowMenu', () => {
  it('opens on trigger click and renders menu content', () => {
    render(
      <OverflowMenu label="更多操作">
        {() => <button type="button">重新分析</button>}
      </OverflowMenu>,
    );

    expect(screen.queryByText('重新分析')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '更多操作' }));
    expect(screen.getByText('重新分析')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '更多操作' })).toHaveAttribute('aria-expanded', 'true');
  });

  it('closes when an item invokes the close callback', () => {
    const onClick = vi.fn();
    render(
      <OverflowMenu label="更多操作">
        {(close) => (
          <button type="button" onClick={() => { onClick(); close(); }}>历史趋势</button>
        )}
      </OverflowMenu>,
    );

    fireEvent.click(screen.getByRole('button', { name: '更多操作' }));
    fireEvent.click(screen.getByText('历史趋势'));
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('历史趋势')).not.toBeInTheDocument();
  });

  it('closes on Escape and on outside click', () => {
    render(
      <div>
        <button type="button">outside</button>
        <OverflowMenu label="更多操作">{() => <span>菜单项</span>}</OverflowMenu>
      </div>,
    );

    fireEvent.click(screen.getByRole('button', { name: '更多操作' }));
    expect(screen.getByText('菜单项')).toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByText('菜单项')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '更多操作' }));
    expect(screen.getByText('菜单项')).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByRole('button', { name: 'outside' }));
    expect(screen.queryByText('菜单项')).not.toBeInTheDocument();
  });
});
