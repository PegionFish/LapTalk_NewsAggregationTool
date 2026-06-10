import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import RelationDialog from '../RelationDialog';

describe('RelationDialog', () => {
  it('renders nothing when closed', () => {
    render(<RelationDialog open={false} onClose={vi.fn()} onSelect={vi.fn()} />);
    expect(screen.queryByText('选择关系类型')).not.toBeInTheDocument();
  });

  it('renders all 5 relation types when open', () => {
    render(<RelationDialog open={true} onClose={vi.fn()} onSelect={vi.fn()} />);
    expect(screen.getByText('选择关系类型')).toBeInTheDocument();
    expect(screen.getByText('之前发生')).toBeInTheDocument();
    expect(screen.getByText('之后发生')).toBeInTheDocument();
    expect(screen.getByText('更新')).toBeInTheDocument();
    expect(screen.getByText('衍生')).toBeInTheDocument();
    expect(screen.getByText('相关')).toBeInTheDocument();
  });

  it('calls onSelect with relation type when clicked', () => {
    const onSelect = vi.fn();
    render(<RelationDialog open={true} onClose={vi.fn()} onSelect={onSelect} />);
    fireEvent.click(screen.getByText('之前发生'));
    expect(onSelect).toHaveBeenCalledWith('before');
  });

  it('calls onClose when backdrop clicked', () => {
    const onClose = vi.fn();
    render(<RelationDialog open={true} onClose={onClose} onSelect={vi.fn()} />);
    const backdrop = screen.getByText('选择关系类型').closest('div')?.parentElement;
    if (backdrop) fireEvent.click(backdrop);
    expect(onClose).toHaveBeenCalled();
  });
});
