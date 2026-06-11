import type { ReactNode, ButtonHTMLAttributes } from 'react';

type ButtonVariant = 'primary' | 'green' | 'purple' | 'orange' | 'ghost';
type ButtonSize = 'sm' | 'xs';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: string;
  loading?: boolean;
  children: ReactNode;
}

const variantClass: Record<ButtonVariant, string> = {
  primary: 'ui-btn--primary',
  green: 'ui-btn--green',
  purple: 'ui-btn--purple',
  orange: 'ui-btn--orange',
  ghost: 'ui-btn--ghost',
};

const sizeClass: Record<ButtonSize, string> = {
  sm: 'ui-btn--sm',
  xs: 'ui-btn--xs',
};

export function Button({
  variant = 'primary',
  size,
  icon,
  loading,
  children,
  className = '',
  disabled,
  ...props
}: ButtonProps) {
  const classes = [
    'ui-btn',
    variantClass[variant],
    size ? sizeClass[size] : '',
    className,
  ].filter(Boolean).join(' ');

  return (
    <button className={classes} disabled={disabled || loading} {...props}>
      {loading ? (
        <i className="fas fa-spinner fa-spin" />
      ) : icon ? (
        <i className={`fas ${icon}`} />
      ) : null}
      {children}
    </button>
  );
}
