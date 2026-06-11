import type { InputHTMLAttributes } from 'react';

interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> {
  inputSize?: 'sm';
}

export function Input({ inputSize, className = '', ...props }: InputProps) {
  return (
    <input
      className={`ui-input ${inputSize === 'sm' ? 'ui-input--sm' : ''} ${className}`}
      {...props}
    />
  );
}
