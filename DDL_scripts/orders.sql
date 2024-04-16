CREATE TABLE public.orders (
	id serial4 NOT NULL,
	user_id int4 NULL,
	"timestamp" timestamp NULL,
	drink varchar NULL,
	price int8 NULL,
	status_id int4 DEFAULT 1 NULL,
	pickup_time varchar NULL
);