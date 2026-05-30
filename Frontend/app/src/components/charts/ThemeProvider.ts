import { Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, BarElement, ArcElement, Title, Tooltip, Legend, Filler } from 'chart.js';

// Register Chart.js components
ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  ArcElement,
  Title,
  Tooltip,
  Legend,
  Filler
);

// Apply custom elegant dark theme defaults
ChartJS.defaults.color = '#8A8A8A';
ChartJS.defaults.font.family = "'Inter', sans-serif";
ChartJS.defaults.font.size = 11;

ChartJS.defaults.plugins.legend.labels.color = '#F5F5F5';
ChartJS.defaults.plugins.legend.labels.boxWidth = 12;
ChartJS.defaults.plugins.legend.labels.boxHeight = 12;

ChartJS.defaults.plugins.tooltip.backgroundColor = '#161616';
ChartJS.defaults.plugins.tooltip.titleColor = '#F5F5F5';
ChartJS.defaults.plugins.tooltip.bodyColor = '#8A8A8A';
ChartJS.defaults.plugins.tooltip.borderColor = '#262626';
ChartJS.defaults.plugins.tooltip.borderWidth = 1;
ChartJS.defaults.plugins.tooltip.padding = 10;
ChartJS.defaults.plugins.tooltip.cornerRadius = 6;

export const ChartColors = {
  primary: '#38BDF8', // Cyan
  primaryDim: 'rgba(56, 189, 248, 0.12)',
  primaryGradStart: 'rgba(56, 189, 248, 0.25)',
  primaryGradStop: 'rgba(56, 189, 248, 0)',

  secondary: '#818CF8', // Indigo
  secondaryDim: 'rgba(129, 140, 248, 0.12)',

  accentCyan: '#22D3EE', // Bright cyan accent
  tertiary: '#34D399', // Emerald / Profit
  profit: '#34D399',
  loss: '#FB7185',

  grid: 'rgba(255, 255, 255, 0.04)',
  textPrimary: '#F1F5F9',
  textSecondary: '#94A3B8',
  textMuted: '#475569',

  background: '#030712',
  surface: 'rgba(15, 23, 42, 0.4)'
};
