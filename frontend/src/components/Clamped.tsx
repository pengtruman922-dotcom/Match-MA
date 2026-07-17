import { Link } from 'react-router-dom';

export function ClampedText({ value, className = '' }: { value: string; className?: string }) {
  return <span title={value === '-' ? undefined : value} className={`line-clamp-2 break-words ${className}`}>{value}</span>;
}

export function ClampedLink({ to, value, className = '' }: { to: string; value: string; className?: string }) {
  return (
    <Link to={to} title={value} className={`line-clamp-2 break-words ${className}`}>
      {value}
    </Link>
  );
}
