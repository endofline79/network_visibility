import { MapPin } from "lucide-react";
import type { Country } from "./types";

export function CountryActivity({
  countries,
  selected,
  onSelect,
  scope,
  emptyMessage,
}: {
  countries: Country[];
  selected: string;
  onSelect: (code: string) => void;
  scope: string;
  emptyMessage: string;
}) {
  const known = countries.filter((country) => country.code !== "??");
  const unknown = countries.find((country) => country.code === "??");
  const row = (country: Country) => {
    const name = country.code === "??" ? "Unknown locations" : country.name;
    const description = `${name}: ${country.count.toLocaleString()} public endpoints · ${country.percent.toFixed(1)}%`;
    return (
      <button
        key={country.code}
        className={"country-row" + (selected === country.code ? " chosen" : "")}
        data-country-code={country.code}
        data-endpoints={country.count}
        onClick={() => onSelect(selected === country.code ? "" : country.code)}
        aria-pressed={selected === country.code}
        aria-label={description}
        title={description}
      >
        <span className="flag" aria-hidden="true">
          {/^[A-Z]{2}$/.test(country.code)
            ? String.fromCodePoint(
                ...[...country.code].map((c) => c.charCodeAt(0) + 127397),
              )
            : "◌"}
        </span>
        <span>{name}</span>
        <span className="bar" aria-hidden="true">
          <span style={{ width: country.percent + "%" }} />
        </span>
        <strong>{country.percent.toFixed(0)}%</strong>
      </button>
    );
  };
  return (
    <section
      className="panel countries"
      aria-labelledby="country-activity-heading"
    >
      <div className="panel-title">
        <div className="title-with-icon">
          <span className="small-icon blue">
            <MapPin />
          </span>
          <div>
            <h2 id="country-activity-heading">Where activity is going</h2>
            <p>Share of public endpoints · {scope}</p>
          </div>
        </div>
        {selected && (
          <button className="text-button" onClick={() => onSelect("")}>
            All countries
          </button>
        )}
      </div>
      {known.length > 0 && (
        <div className="country-list" aria-label="Observed countries">
          {known.map(row)}
        </div>
      )}
      {unknown && <div className="country-unknown">{row(unknown)}</div>}
      {!countries.length && <p className="empty">{emptyMessage}</p>}
    </section>
  );
}
