export const site = {
  name: 'Jonathan Ziesmer',
  role: 'Software Engineer',
  email: 'jztrailg@gmail.com',
  linkedin: 'https://www.linkedin.com/in/jonathan-ziesmer/',
  github: 'https://github.com/jonathan1440',
  url: 'https://jonathanziesmer.com',
  resumePath: '/resume.pdf',
  description:
    'Software engineer working in Python, TypeScript, and AWS. Portfolio and resume for Jonathan Ziesmer.',
} as const;

export const nav = [
  { href: '/about', label: 'About' },
  { href: '/experience', label: 'Experience' },
  { href: '/projects', label: 'Projects' },
  { href: '/contact', label: 'Contact' },
] as const;
