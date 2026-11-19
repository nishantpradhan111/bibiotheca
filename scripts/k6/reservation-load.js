import http from "k6/http";
import { check, sleep } from "k6";

// Keep the test read-only so concurrent virtual users never create invalid holds.
export const options = {
  stages: [
    { duration: "1m", target: 10 },
    { duration: "3m", target: 40 },
    { duration: "1m", target: 40 },
    { duration: "1m", target: 0 },
  ],
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<800"],
  },
};

// Fail early when the target URL or existing fixture IDs were not supplied.
export function setup() {
  if (!__ENV.BASE_URL || !__ENV.BOOK_ID || !__ENV.MEMBER_ID) {
    throw new Error("Set BASE_URL, BOOK_ID, and MEMBER_ID before running this test");
  }
  return {
    base: __ENV.BASE_URL.replace(/\/$/, ""),
    bookId: encodeURIComponent(__ENV.BOOK_ID),
    memberId: encodeURIComponent(__ENV.MEMBER_ID),
  };
}

// Exercise Catalog, Availability, and the Reservation HPA using existing records.
export default function (fixtures) {
  const catalog = http.get(`${fixtures.base}/books?limit=20`);
  check(catalog, { "catalog list responds": (response) => response.status === 200 });

  const availability = http.get(`${fixtures.base}/books/${fixtures.bookId}/availability`);
  check(availability, { "book availability responds": (response) => response.status === 200 });

  const reservations = http.get(
    `${fixtures.base}/reservations?member_id=${fixtures.memberId}&limit=20`,
  );
  check(reservations, { "member reservation list responds": (response) => response.status === 200 });
  sleep(0.2);
}
